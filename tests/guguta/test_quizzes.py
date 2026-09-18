"""Quiz generation, hidden answers, grading, results and retake."""

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
async def quiz_client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(
        _config(guguta_db["api_dsn"]).model_copy(update={"chat_provider": "mock"})
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3000"
    ) as client:
        yield client


@pytest_asyncio.fixture()
async def quiz_worker(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    from open_notebook.database.guguta.engine import create_engine_for_role
    from open_notebook.jobs.guguta.embeddings import HashEmbeddingProvider
    from open_notebook.jobs.guguta.worker import Worker
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    class TestWorker(Worker):
        def __init__(self):
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
async def test_quiz_generation_grading_results_and_retake(
    quiz_client: AsyncClient, quiz_worker: Any
) -> None:
    auth = await _login(quiz_client, f"Elev Quiz {uuid.uuid4().hex[:6]}")
    notebook = (
        await quiz_client.post(
            "/api/v1/notebooks",
            json={"title": "Științe"},
            cookies=_cookies(auth),
            headers=_headers(auth),
        )
    ).json()
    source = await quiz_client.post(
        f"/api/v1/notebooks/{notebook['id']}/sources/text",
        json={
            "title": "Fotosinteza",
            "text": "Fotosinteza transformă energia luminii în energie chimică. Clorofila absoarbe lumina.",
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert source.status_code == 201
    await _drain(quiz_worker)
    source_id = source.json()["source"]["id"]
    created = await quiz_client.post(
        f"/api/v1/notebooks/{notebook['id']}/quizzes",
        json={
            "source_ids": [source_id],
            "quantity": "fewer",
            "difficulty": "medium",
            "question_types": ["multiple_choice"],
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert created.status_code == 202, created.text
    quiz_id = created.json()["id"]
    assert await quiz_worker.process_one()
    detail = await quiz_client.get(
        f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}", cookies=_cookies(auth)
    )
    assert detail.status_code == 200
    quiz = detail.json()
    assert quiz["status"] == "ready" and quiz["questions"]
    question = quiz["questions"][0]
    assert (
        "is_correct" not in question["options"][0]
        and "reference_answer" not in question
    )
    attempt = (
        await quiz_client.post(
            f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}/attempts",
            cookies=_cookies(auth),
            headers=_headers(auth),
        )
    ).json()
    answer = await quiz_client.post(
        f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}/attempts/{attempt['id']}/answers",
        json={"question_id": question["id"], "response": "a", "hint_used": True},
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["result"]["status"] == "correct"
    results = await quiz_client.get(
        f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}/attempts/{attempt['id']}/results",
        cookies=_cookies(auth),
    )
    assert results.json()["score"] == 1.0
    explain = await quiz_client.post(
        f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}/questions/{question['id']}/explain",
        json={"response": "a"},
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert explain.status_code == 200
    retake = await quiz_client.post(
        f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}/attempts",
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert retake.status_code == 201 and retake.json()["id"] != attempt["id"]
    deleted = await quiz_client.delete(
        f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}",
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert deleted.json() == {"deleted": True}
