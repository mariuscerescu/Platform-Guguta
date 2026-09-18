"""Audio Overview API + durable worker integration."""

from __future__ import annotations

import io
import json
import uuid
import wave
from types import SimpleNamespace
from typing import Any, AsyncIterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from open_notebook.ai.guguta.audio_overview import (
    MossTtsClient,
    concatenate_wav,
    split_for_speech,
)
from open_notebook.database.guguta.config import GugutaConfig
from tests.guguta.test_materials_worker import (
    _config,
    _cookies,
    _drain,
    _headers,
    _login,
)


def _wav(seconds: float = 0.04, rate: int = 48_000) -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\0\0\0\0" * int(seconds * rate))
    return target.getvalue()


@pytest_asyncio.fixture()
async def audio_client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(_config(guguta_db["api_dsn"]))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3000"
    ) as client:
        yield client


@pytest_asyncio.fixture()
async def audio_worker(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    from open_notebook.database.guguta.engine import create_engine_for_role
    from open_notebook.jobs.guguta.embeddings import HashEmbeddingProvider
    from open_notebook.jobs.guguta.worker import Worker
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    class TestWorker(Worker):
        def __init__(self) -> None:
            cfg = _config(guguta_db["worker_dsn"])
            self._config = cfg
            self._engine = create_engine_for_role(cfg, "worker")
            self._storage = FilesystemStorage("./.guguta-test-storage")
            self._provider = HashEmbeddingProvider(dimension=8)
            self._stopping = __import__("asyncio").Event()

    instance = TestWorker()
    yield instance
    await instance.aclose()


def test_audio_helpers_split_and_join() -> None:
    text = "Prima propoziție. " + "A doua propoziție este mai lungă. " * 20
    parts = split_for_speech(text, max_chars=180)
    assert len(parts) > 1
    assert " ".join(parts).replace("  ", " ") == text.strip().replace("  ", " ")
    combined, duration = concatenate_wav([_wav(), _wav()])
    assert combined.startswith(b"RIFF")
    assert 0.07 <= duration <= 0.09


@pytest.mark.asyncio
async def test_moss_client_uses_exact_local_model_and_romanian() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=_wav())

    client = MossTtsClient(
        SimpleNamespace(
            moss_tts_base_url="http://moss-tts:8000",
            moss_tts_timeout_seconds=10,
        ),
        transport=httpx.MockTransport(handler),
    )
    audio, duration = await client.synthesize("Aceasta este o explicație scurtă.")
    assert audio.startswith(b"RIFF")
    assert duration > 0
    assert seen[0]["model"] == "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"
    assert seen[0]["language"] == "Romanian"


@pytest.mark.asyncio
async def test_audio_overview_end_to_end(
    audio_client: AsyncClient,
    audio_worker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_synthesize(self: MossTtsClient, script: str) -> tuple[bytes, float]:
        assert "fotosinte" in script.lower()
        return _wav(0.1), 0.1

    monkeypatch.setattr(MossTtsClient, "synthesize", fake_synthesize)

    auth = await _login(audio_client, f"Elev Audio {uuid.uuid4().hex[:6]}")
    notebook = (
        await audio_client.post(
            "/api/v1/notebooks",
            json={"title": "Biologie"},
            cookies=_cookies(auth),
            headers=_headers(auth),
        )
    ).json()
    source_response = await audio_client.post(
        f"/api/v1/notebooks/{notebook['id']}/sources/text",
        json={
            "title": "Fotosinteza",
            "text": "Fotosinteza transformă energia luminii în energie chimică pentru plante.",
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert source_response.status_code == 201, source_response.text
    await _drain(audio_worker)
    source_id = source_response.json()["source"]["id"]

    created = await audio_client.post(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews",
        json={"format": "brief", "source_ids": [source_id]},
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert created.status_code == 202, created.text
    overview_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    assert await audio_worker.process_one()
    items = await audio_client.get(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews",
        cookies=_cookies(auth),
    )
    assert items.status_code == 200
    assert items.json()[0]["id"] == overview_id
    assert items.json()[0]["status"] == "ready"

    audio = await audio_client.get(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews/{overview_id}/audio",
        cookies=_cookies(auth),
    )
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert audio.content.startswith(b"RIFF")


def test_moss_url_must_be_local() -> None:
    with pytest.raises(ValueError, match="local MOSS-TTS"):
        GugutaConfig(moss_tts_base_url="https://remote.example/tts")
