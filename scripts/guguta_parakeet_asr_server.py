"""Private FastAPI server for gabrielpirlo/Sped_ParakeetRomanian_110M_TDT-CTC."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile

MODEL_ID = os.getenv(
    "PARAKEET_ASR_MODEL_ID",
    "gabrielpirlo/Sped_ParakeetRomanian_110M_TDT-CTC",
)
MODEL_FILE = os.getenv(
    "PARAKEET_ASR_MODEL_FILE", "SpeD-ParakeetRo_110M_TDT-CTC.nemo"
)
DEVICE = os.getenv("PARAKEET_ASR_DEVICE", "cuda:0")
MAX_AUDIO_BYTES = int(os.getenv("PARAKEET_ASR_MAX_AUDIO_MIB", "15")) * 1024 * 1024

app = FastAPI(title="Guguță Romanian ASR", docs_url=None, redoc_url=None)
_model: Any = None
_inference_lock = asyncio.Lock()


def _load_model() -> Any:
    import torch
    from huggingface_hub import hf_hub_download
    from nemo.collections.asr.models import ASRModel

    checkpoint = hf_hub_download(repo_id=MODEL_ID, filename=MODEL_FILE)
    model = ASRModel.restore_from(restore_path=checkpoint, map_location=DEVICE)
    model.eval()
    if DEVICE.startswith("cuda"):
        model = model.to(torch.device(DEVICE))
    return model


@app.on_event("startup")
async def startup() -> None:
    global _model
    _model = await asyncio.to_thread(_load_model)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    if _model is None:
        raise HTTPException(status_code=503, detail="model-loading")
    return {"status": "ok", "model": MODEL_ID}


def _transcript_text(result: Any) -> str:
    if isinstance(result, (list, tuple)):
        if not result:
            return ""
        result = result[0]
    if isinstance(result, str):
        return result.strip()
    return str(getattr(result, "text", "") or "").strip()


def _run_transcription(source: Path, workdir: Path) -> str:
    normalized = workdir / "recording.wav"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(source), "-ac", "1", "-ar", "16000", str(normalized),
        ],
        check=True,
        timeout=45,
    )
    return _transcript_text(_model.transcribe([str(normalized)], batch_size=1))


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict[str, str]:
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="invalid-audio-size")

    suffix = Path(file.filename or "recording.webm").suffix[:10] or ".webm"
    try:
        with tempfile.TemporaryDirectory(prefix="guguta-asr-") as directory:
            workdir = Path(directory)
            source = workdir / f"input{suffix}"
            source.write_bytes(data)
            async with _inference_lock:
                text = await asyncio.to_thread(_run_transcription, source, workdir)
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(status_code=422, detail="invalid-audio") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="transcription-failed") from exc

    return {"text": text}
