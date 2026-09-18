"""Private MOSS-TTS service used by the Guguță audio-overview worker.

The service deliberately exposes only the small OpenAI-compatible subset that
the worker needs.  It loads the validated Romanian reference voice once and
serializes inference because one Tesla T4 cannot hold the speech model and the
48 kHz codec on the GPU at the same time.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from transformers import AutoModel, AutoProcessor

MOSS_MODEL = "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"


class VoiceReference(BaseModel):
    audio_path: str
    text: str | None = None


class SpeechRequest(BaseModel):
    input: Annotated[str, Field(min_length=1, max_length=2_000)]
    model: str = MOSS_MODEL
    voice: str = "default"
    language: str = "Romanian"
    instructions: str | None = None
    references: list[VoiceReference] = Field(default_factory=list, max_length=1)
    response_format: Literal["wav"] = "wav"
    stream: Literal[False] = False


class MossRomanianEngine:
    def __init__(self) -> None:
        runtime_root = Path(
            os.environ.get("MOSS_TTS_RUNTIME_ROOT", "/opt/moss-runtime")
        )
        self.model_path = Path(
            os.environ.get(
                "MOSS_TTS_MODEL_PATH",
                str(runtime_root / "models/MOSS-TTS-Local-Transformer-v1.5"),
            )
        )
        self.codec_path = Path(
            os.environ.get(
                "MOSS_TTS_CODEC_PATH",
                str(runtime_root / "models/MOSS-Audio-Tokenizer-v2"),
            )
        )
        self.reference_path = Path(
            os.environ.get("MOSS_TTS_REFERENCE_AUDIO", "/voices/romanian.wav")
        )
        self.reference_api_path = os.environ.get(
            "MOSS_TTS_REFERENCE_API_PATH", "/voices/romanian.wav"
        )
        self.device = torch.device(os.environ.get("MOSS_TTS_DEVICE", "cuda:0"))
        self.processor = None
        self.model = None
        self.reference_codes = None
        self._lock = asyncio.Lock()

    def load(self) -> None:
        for path, label in (
            (self.model_path, "model"),
            (self.codec_path, "codec"),
            (self.reference_path, "Romanian reference voice"),
        ):
            if not path.exists():
                raise FileNotFoundError(f"Missing {label}: {path}")
        if not torch.cuda.is_available():
            raise RuntimeError("MOSS-TTS requires a CUDA GPU")

        torch.manual_seed(20260828)
        torch.cuda.manual_seed_all(20260828)
        torch.backends.cuda.enable_cudnn_sdp(False)
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(True)

        self.processor = AutoProcessor.from_pretrained(
            self.model_path,
            codec_path=str(self.codec_path),
            codec_weight_dtype="bf16",
            trust_remote_code=True,
        )
        self.processor.audio_tokenizer = self.processor.audio_tokenizer.to(self.device)
        self.processor.audio_tokenizer.eval()
        waveform, sample_rate = sf.read(
            self.reference_path, dtype="float32", always_2d=True
        )
        reference_waveform = torch.from_numpy(waveform.T.copy())
        with torch.inference_mode():
            self.reference_codes = self.processor.encode_audios_from_wav(
                reference_waveform, sample_rate
            )[0]
        self.processor.audio_tokenizer = self.processor.audio_tokenizer.to("cpu")
        torch.cuda.empty_cache()

        attention = "sdpa"
        if importlib.util.find_spec("flash_attn") is not None:
            major, _ = torch.cuda.get_device_capability(self.device)
            if major >= 8:
                attention = "flash_attention_2"
        self.model = AutoModel.from_pretrained(
            self.model_path,
            trust_remote_code=True,
            local_files_only=True,
            attn_implementation=attention,
            dtype=torch.bfloat16,
        ).to(self.device)
        self.model.eval()

    def _validate_request(self, request: SpeechRequest) -> None:
        if request.model != MOSS_MODEL:
            raise ValueError(f"Unsupported model: {request.model}")
        if request.language.casefold() != "romanian":
            raise ValueError("This private endpoint only serves Romanian speech")
        if not request.references:
            raise ValueError("A Romanian reference voice is required")
        if request.references[0].audio_path != self.reference_api_path:
            raise ValueError("The requested reference voice is not available")

    def synthesize(self, request: SpeechRequest) -> bytes:
        self._validate_request(request)
        assert self.processor is not None
        assert self.model is not None
        assert self.reference_codes is not None

        conversation = [
            self.processor.build_user_message(
                text=request.input,
                reference=[self.reference_codes],
                language="Romanian",
            )
        ]
        batch = self.processor([conversation], mode="generation")
        max_new_tokens = max(256, min(1_024, int(len(request.input) * 1.6)))
        with torch.inference_mode():
            outputs = self.model.generate(
                input_ids=batch["input_ids"].to(self.device),
                attention_mask=batch["attention_mask"].to(self.device),
                max_new_tokens=max_new_tokens,
                do_sample=True,
                audio_temperature=1.7,
                audio_top_p=0.8,
                audio_top_k=25,
                audio_repetition_penalty=1.0,
            )

        # A T4 cannot keep both networks resident.  Move the generator aside,
        # decode on CUDA, then restore the hot state for the next request.
        self.model = self.model.to("cpu")
        torch.cuda.empty_cache()
        try:
            self.processor.audio_tokenizer = self.processor.audio_tokenizer.to(
                self.device
            )
            self.processor.audio_tokenizer.eval()
            with torch.inference_mode():
                message = self.processor.decode(outputs)[0]
            if message is None or not message.audio_codes_list:
                raise RuntimeError("MOSS-TTS did not return decodable audio")
            audio = message.audio_codes_list[0].detach().float().cpu()
            if audio.ndim == 1:
                audio = audio.unsqueeze(0)
            target = io.BytesIO()
            sf.write(
                target,
                audio.transpose(0, 1).numpy(),
                self.processor.model_config.sampling_rate,
                format="WAV",
                subtype="PCM_16",
            )
            return target.getvalue()
        finally:
            self.processor.audio_tokenizer = self.processor.audio_tokenizer.to("cpu")
            torch.cuda.empty_cache()
            self.model = self.model.to(self.device)
            self.model.eval()

    async def synthesize_serialized(self, request: SpeechRequest) -> bytes:
        async with self._lock:
            return await asyncio.to_thread(self.synthesize, request)


engine = MossRomanianEngine()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(engine.load)
    yield


app = FastAPI(title="Guguță Romanian MOSS-TTS", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "model": MOSS_MODEL, "language": "Romanian"}


@app.post("/v1/audio/speech")
async def speech(request: SpeechRequest) -> Response:
    try:
        audio = await engine.synthesize_serialized(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav")
