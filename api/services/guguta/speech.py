"""Authenticated speech-to-text bridge for the private Romanian ASR service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import BinaryIO

import httpx


class SpeechValidation(ValueError):
    pass


class SpeechUnavailable(RuntimeError):
    pass


_ALLOWED_AUDIO_TYPES = {
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "video/webm",
}


class SpeechService:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        max_audio_mib: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_bytes = max_audio_mib * 1024 * 1024
        self._transport = transport

    async def transcribe(
        self,
        *,
        stream: BinaryIO,
        filename: str | None,
        content_type: str | None,
    ) -> dict[str, str]:
        mime = (content_type or "").split(";", 1)[0].strip().lower()
        if mime not in _ALLOWED_AUDIO_TYPES:
            raise SpeechValidation("Format audio neacceptat.")

        data = await asyncio.to_thread(stream.read, self._max_bytes + 1)
        if not data:
            raise SpeechValidation("Înregistrarea audio este goală.")
        if len(data) > self._max_bytes:
            raise SpeechValidation("Înregistrarea audio este prea mare.")

        safe_name = Path(filename or "recording.webm").name
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/transcribe",
                    files={"file": (safe_name, data, mime)},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SpeechUnavailable(
                "Serviciul de transcriere nu este disponibil. Încearcă din nou."
            ) from exc

        text = str(payload.get("text") or "").strip()
        if not text:
            raise SpeechValidation("Nu am detectat vorbire în înregistrare.")
        return {"text": text}
