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

from api.routers.guguta_v1 import _audio_download_response
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


def test_audio_download_response_supports_browser_byte_ranges() -> None:
    data = b"RIFF0123456789"

    complete = _audio_download_response(data, "audio/wav", "Lecție.wav", None)
    assert complete.status_code == 200
    assert complete.body == data
    assert complete.headers["accept-ranges"] == "bytes"
    assert complete.headers["content-length"] == str(len(data))

    bounded = _audio_download_response(
        data, "audio/wav", "Lecție.wav", "bytes=4-7"
    )
    assert bounded.status_code == 206
    assert bounded.body == b"0123"
    assert bounded.headers["content-range"] == f"bytes 4-7/{len(data)}"
    assert bounded.headers["content-length"] == "4"

    open_ended = _audio_download_response(
        data, "audio/wav", "Lecție.wav", "bytes=10-"
    )
    assert open_ended.status_code == 206
    assert open_ended.body == data[10:]

    suffix = _audio_download_response(
        data, "audio/wav", "Lecție.wav", "bytes=-4"
    )
    assert suffix.status_code == 206
    assert suffix.body == data[-4:]


@pytest.mark.parametrize(
    "range_header",
    ["items=0-1", "bytes=99-", "bytes=5-4", "bytes=0-1,3-4", "bytes=-0"],
)
def test_audio_download_response_rejects_invalid_ranges(range_header: str) -> None:
    data = b"RIFF0123456789"
    response = _audio_download_response(data, "audio/wav", "audio.wav", range_header)
    assert response.status_code == 416
    assert response.body == b""
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes */{len(data)}"


@pytest.mark.asyncio
async def test_moss_client_uses_exact_local_model_and_romanian() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=_wav())

    client = MossTtsClient(
        SimpleNamespace(
            moss_tts_base_url="http://moss-tts:8000",
            moss_tts_reference_audio="/voices/romanian.wav",
            moss_tts_timeout_seconds=10,
        ),
        transport=httpx.MockTransport(handler),
    )
    audio, duration = await client.synthesize("Aceasta este o explicație scurtă.")
    assert audio.startswith(b"RIFF")
    assert duration > 0
    assert seen[0]["model"] == "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"
    assert seen[0]["language"] == "Romanian"
    assert seen[0]["references"] == [
        {"audio_path": "/voices/romanian.wav"}
    ]


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
        json={
            "format": "brief",
            "source_ids": [source_id],
            "instructions": "Concentrează-te pe rolul luminii.",
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert created.status_code == 202, created.text
    overview_id = created.json()["id"]
    assert created.json()["status"] == "queued"
    assert created.json()["instructions"] == "Concentrează-te pe rolul luminii."

    assert await audio_worker.process_one()
    items = await audio_client.get(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews",
        cookies=_cookies(auth),
    )
    assert items.status_code == 200
    assert items.json()[0]["id"] == overview_id
    assert items.json()[0]["status"] == "ready"
    assert items.json()[0]["instructions"] == "Concentrează-te pe rolul luminii."

    audio = await audio_client.get(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews/{overview_id}/audio",
        cookies=_cookies(auth),
    )
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert audio.headers["accept-ranges"] == "bytes"
    assert audio.content.startswith(b"RIFF")

    partial = await audio_client.get(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews/{overview_id}/audio",
        cookies=_cookies(auth),
        headers={"Range": "bytes=0-3"},
    )
    assert partial.status_code == 206
    assert partial.content == b"RIFF"
    assert partial.headers["content-range"] == f"bytes 0-3/{len(audio.content)}"
    assert partial.headers["content-length"] == "4"

    deleted = await audio_client.delete(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews/{overview_id}",
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert (
        await audio_client.get(
            f"/api/v1/notebooks/{notebook['id']}/audio-overviews",
            cookies=_cookies(auth),
        )
    ).json() == []
    assert (
        await audio_client.get(
            f"/api/v1/notebooks/{notebook['id']}/audio-overviews/{overview_id}/audio",
            cookies=_cookies(auth),
        )
    ).status_code == 404

    queued = await audio_client.post(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews",
        json={"format": "brief", "source_ids": [source_id]},
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert queued.status_code == 202
    cancelled = await audio_client.delete(
        f"/api/v1/notebooks/{notebook['id']}/audio-overviews/{queued.json()['id']}",
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert cancelled.json() == {"deleted": True}
    assert not await audio_worker.process_one()


def test_moss_url_must_be_local() -> None:
    with pytest.raises(ValueError, match="local MOSS-TTS"):
        GugutaConfig(moss_tts_base_url="https://remote.example/tts")


def test_moss_reference_must_be_server_local_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute server-local path"):
        GugutaConfig(moss_tts_reference_audio="../romanian.wav")
