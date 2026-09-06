from __future__ import annotations

from collections.abc import AsyncIterator

"""Audit lot 2 regression tests: F07, F09, F10."""

import uuid
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from open_notebook.ai.guguta.chat import ChatAnswer
from open_notebook.database.guguta.engine import (
    actor_connection,
    create_engine_for_role,
)
from open_notebook.jobs.guguta.embeddings import HashEmbeddingProvider
from open_notebook.jobs.guguta.handlers import process_material_version
from open_notebook.jobs.guguta.queue import claim, enqueue
from open_notebook.storage.guguta.filesystem import FilesystemStorage
from tests.guguta.test_materials_worker import _config, _drain

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def guguta_app(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    api = pytest.importorskip("api.guguta_app")
    yield api.create_guguta_app(_config(guguta_db["api_dsn"]))


@pytest_asyncio.fixture()
async def client(guguta_app: Any) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=guguta_app), base_url="http://localhost:3000"
    ) as c:
        yield c


@pytest_asyncio.fixture()
async def worker(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    from open_notebook.jobs.guguta.worker import Worker

    class TestWorker(Worker):
        def __init__(self) -> None:
            cfg = _config(guguta_db["worker_dsn"])
            self._config = cfg
            self._engine = create_engine_for_role(cfg, "worker")
            self._storage = FilesystemStorage("./.guguta-test-storage")
            self._provider = HashEmbeddingProvider(dimension=8)
            self._stopping = __import__("asyncio").Event()

    w = TestWorker()
    yield w
    await w.aclose()


def _headers(auth: dict[str, str]) -> dict[str, str]:
    return {"X-Guguta-CSRF": auth["csrf"], "Origin": "http://localhost:3000"}


def _cookies(auth: dict[str, str]) -> dict[str, str]:
    return {"guguta_session": auth["cookie"]}


async def _login(client: AsyncClient, name: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/dev-login",
        json={"display_name": name},
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200
    return {
        "csrf": resp.headers.get("X-Guguta-CSRF", ""),
        "cookie": resp.cookies.get("guguta_session", ""),
    }


async def _setup_nb_with_source(
    client: AsyncClient, worker: Any, marker: str
) -> tuple[dict[str, str], str]:
    auth = await _login(client, f"User {uuid.uuid4().hex[:6]}")
    nb = (await client.post(
        "/api/v1/notebooks", json={"title": f"Carnet {marker}"},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={"title": "sursa", "text": f"{marker} este conținutul de test."},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    await _drain(worker)
    return auth, nb["id"]


async def test_f07_history_excludes_old_revision(
    guguta_app: Any, client: AsyncClient, worker: Any
) -> None:
    """F07: after removing a source, the next generation's MODEL context
    excludes history generated under the old revision (A17)."""
    auth, nb_id = await _setup_nb_with_source(client, worker, "SECRET_OLD_AUDIT")
    session = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions", json={},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    r1 = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        json={"content": "SECRET_OLD_AUDIT"},
        cookies=_cookies(auth), headers=_headers(auth),
    ))
    assert r1.status_code == 200

    sources = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sources", cookies=_cookies(auth)
    )).json()
    await client.delete(
        f"/api/v1/notebooks/{nb_id}/sources/{sources[0]['id']}",
        cookies=_cookies(auth), headers=_headers(auth),
    )
    await client.post(
        f"/api/v1/notebooks/{nb_id}/sources/text",
        json={"title": "sursa nouă", "text": "SUBIECT_NOU este topicul actual."},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    await _drain(worker)

    captured: dict[str, Any] = {}

    class CapturingProvider:
        model_name = "capture"

        def generate(self, question, context_chunks, history):
            captured["history"] = list(history)
            captured["context"] = [c.text for c in context_chunks]
            return ChatAnswer(content="ok", cited=[], model=self.model_name)

    guguta_app.state.guguta_chat._provider = CapturingProvider()
    sess2 = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions", json={},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{sess2['id']}/messages",
        json={"content": "SUBIECT_NOU"},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    blob = str(captured)
    assert "SECRET_OLD_AUDIT" not in blob, (
        f"old-revision content leaked into the model context: {blob[:400]}"
    )


async def test_f09_retry_after_provider_failure(
    guguta_app: Any, client: AsyncClient, worker: Any
) -> None:
    """F09: provider fails once → 502; retry with the same key completes the
    operation exactly once."""
    from open_notebook.ai.guguta.chat import MockChatProvider

    auth, nb_id = await _setup_nb_with_source(client, worker, "F09")
    session = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions", json={},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()

    calls = {"n": 0}

    class FlakyProvider(MockChatProvider):
        model_name = "flaky"

        def generate(self, *a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("provider down once")
            return super().generate(*a, **k)

    guguta_app.state.guguta_chat._provider = FlakyProvider()
    key = uuid.uuid4().hex
    r1 = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        json={"content": "F09", "idempotency_key": key},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert r1.status_code == 502
    r2 = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        json={"content": "F09", "idempotency_key": key},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert r2.status_code == 200, r2.text
    assert calls["n"] == 2
    msgs = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        cookies=_cookies(auth),
    )).json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) == 1, "duplicate user message after retry"


async def test_f10_stale_worker_cannot_publish(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    """F10: a worker whose lease was stolen cannot publish artifacts."""
    auth, nb_id = await _setup_nb_with_source(client, worker, "F10")
    me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
    sources = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sources", cookies=_cookies(auth)
    )).json()
    mv_id = uuid.UUID(sources[0]["material_version_id"])
    actor_id = uuid.UUID(me["id"])

    # enqueue a fresh job on the same material version
    api_engine = create_engine_for_role(_config(guguta_db["api_dsn"]), "api")
    async with actor_connection(api_engine, actor_id) as conn:
        await enqueue(
            api_engine, conn,
            job_type="process_material_version",
            target_type="material_version",
            target_id=mv_id,
            actor_id=actor_id,
            payload={"local_name": "F10"},
        )
    await api_engine.dispose()

    # count artifacts before the stale attempt
    eng = sa.create_engine(guguta_db["migrator_dsn"])
    with eng.connect() as conn:
        before = conn.execute(
            sa.text(
                "SELECT count(*) FROM processing_artifacts"
                " WHERE material_version_id = :mv"
            ),
            {"mv": mv_id},
        ).scalar_one()
    eng.dispose()

    # claim with worker #1
    worker_engine = create_engine_for_role(_config(guguta_db["worker_dsn"]), "worker")
    job1 = await claim(worker_engine)
    assert job1 is not None, "worker #1 must claim the queued job"

    # steal the lease: expire it via SQL, then worker #2 claims it
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "UPDATE processing_jobs SET lease_until = now() - interval '1 hour'"
            f" WHERE id = '{job1.id}'"
        )
        conn.commit()
    eng.dispose()

    job2_engine = create_engine_for_role(_config(guguta_db["worker_dsn"]), "worker")
    job2 = await claim(job2_engine)
    assert job2 is not None and job2.id == job1.id
    assert job2.lease_token != job1.lease_token

    # stale worker (old token) runs the handler: fenced → no publication
    stale_engine = create_engine_for_role(_config(guguta_db["worker_dsn"]), "worker")
    await process_material_version(
        stale_engine,
        FilesystemStorage("./.guguta-test-storage"),
        HashEmbeddingProvider(dimension=8),
        job1,
    )

    with eng.connect() as conn:
        after = conn.execute(
            sa.text(
                "SELECT count(*) FROM processing_artifacts"
                " WHERE material_version_id = :mv"
            ),
            {"mv": mv_id},
        ).scalar_one()
    eng.dispose()
    assert after == before, "stale worker published artifacts despite stolen lease"
    await stale_engine.dispose()
    await worker_engine.dispose()
