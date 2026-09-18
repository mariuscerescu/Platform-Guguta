"""Flashcard deck API, worker and study-session integration."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.guguta.test_materials_worker import (
    _config,
    _cookies,
    _drain,
    _headers,
    _login,
)


@pytest_asyncio.fixture()
async def flashcard_client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(
        _config(guguta_db["api_dsn"]).model_copy(update={"chat_provider": "mock"})
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
        yield client


@pytest_asyncio.fixture()
async def flashcard_worker(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    from open_notebook.database.guguta.engine import create_engine_for_role
    from open_notebook.jobs.guguta.embeddings import HashEmbeddingProvider
    from open_notebook.jobs.guguta.worker import Worker
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    class TestWorker(Worker):
        def __init__(self) -> None:
            cfg = _config(guguta_db["worker_dsn"]).model_copy(
                update={"chat_provider": "mock"}
            )
            self._config = cfg
            self._engine = create_engine_for_role(cfg, "worker")
            self._storage = FilesystemStorage("./.guguta-test-storage")
            self._provider = HashEmbeddingProvider(dimension=8)
            self._stopping = __import__("asyncio").Event()

    worker = TestWorker()
    yield worker
    await worker.aclose()


@pytest.mark.asyncio
async def test_flashcards_generate_study_export_and_delete(
    flashcard_client: AsyncClient, flashcard_worker: Any
) -> None:
    auth = await _login(flashcard_client, f"Elev Carduri {uuid.uuid4().hex[:6]}")
    notebook = (await flashcard_client.post(
        "/api/v1/notebooks", json={"title": "Biologie"},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    source_response = await flashcard_client.post(
        f"/api/v1/notebooks/{notebook['id']}/sources/text",
        json={"title": "Fotosinteza", "text": (
            "Fotosinteza transformă energia luminii în energie chimică. "
            "Clorofila absoarbe lumina, iar plantele folosesc dioxid de carbon și apă."
        )}, cookies=_cookies(auth), headers=_headers(auth),
    )
    assert source_response.status_code == 201
    await _drain(flashcard_worker)
    source_id = source_response.json()["source"]["id"]

    created = await flashcard_client.post(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks",
        json={"source_ids": [source_id], "quantity": "fewer", "difficulty": "easy"},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert created.status_code == 202, created.text
    deck_id = created.json()["id"]
    assert await flashcard_worker.process_one()

    detail = await flashcard_client.get(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks/{deck_id}", cookies=_cookies(auth)
    )
    assert detail.status_code == 200, detail.text
    deck = detail.json()
    assert deck["status"] == "ready"
    assert deck["cards"]
    assert deck["cards"][0]["evidence"][0]["source_id"] == source_id
    explanation = await flashcard_client.post(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks/{deck_id}/cards/"
        f"{deck['cards'][0]['id']}/explain",
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert explanation.status_code == 200
    assert "explicație" in explanation.json()["explanation"].lower()

    session_response = await flashcard_client.post(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks/{deck_id}/sessions",
        json={"mode": "all"}, cookies=_cookies(auth), headers=_headers(auth),
    )
    assert session_response.status_code == 201
    session = session_response.json()
    card_id = session["card_order"][0]
    progress = await flashcard_client.patch(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks/{deck_id}/sessions/{session['id']}",
        json={"current_index": 0, "results": {card_id: "missed"}, "completed": True},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert progress.status_code == 200, progress.text
    assert progress.json()["results"][card_id] == "missed"

    missed = await flashcard_client.post(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks/{deck_id}/sessions",
        json={"mode": "missed"}, cookies=_cookies(auth), headers=_headers(auth),
    )
    assert missed.status_code == 201
    assert missed.json()["card_order"] == [card_id]

    exported = await flashcard_client.get(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks/{deck_id}/export.csv",
        cookies=_cookies(auth),
    )
    assert exported.status_code == 200
    assert b"front,back,concept,sources" in exported.content

    deleted = await flashcard_client.delete(
        f"/api/v1/notebooks/{notebook['id']}/flashcard-decks/{deck_id}",
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert deleted.json() == {"deleted": True}
