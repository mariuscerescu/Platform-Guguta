from __future__ import annotations

from io import BytesIO

import httpx
import pytest

from api.services.guguta.speech import SpeechService, SpeechValidation


@pytest.mark.asyncio
async def test_speech_service_forwards_audio_and_returns_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transcribe"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        return httpx.Response(200, json={"text": "  Bună ziua, Guguță.  "})

    service = SpeechService(
        "http://parakeet-asr:8001",
        timeout_seconds=5,
        max_audio_mib=1,
        transport=httpx.MockTransport(handler),
    )
    result = await service.transcribe(
        stream=BytesIO(b"webm-audio"),
        filename="recording.webm",
        content_type="audio/webm;codecs=opus",
    )
    assert result == {"text": "Bună ziua, Guguță."}


@pytest.mark.asyncio
async def test_speech_service_rejects_invalid_or_oversized_audio() -> None:
    service = SpeechService(
        "http://parakeet-asr:8001", timeout_seconds=5, max_audio_mib=1
    )
    with pytest.raises(SpeechValidation, match="Format"):
        await service.transcribe(
            stream=BytesIO(b"x"), filename="x.txt", content_type="text/plain"
        )
    with pytest.raises(SpeechValidation, match="prea mare"):
        await service.transcribe(
            stream=BytesIO(b"x" * (1024 * 1024 + 1)),
            filename="large.webm",
            content_type="audio/webm",
        )
