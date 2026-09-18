"""L4 tests: search, chat with validated citations, and the full two-user
probe (upload â†’ process â†’ search â†’ chat/citation â†’ isolation â†’ restart)."""

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
    _headers,
    _login,
    _make_pdf,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(_config(guguta_db["api_dsn"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:3000") as c:
        yield c


@pytest_asyncio.fixture()
async def worker(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
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

    w = TestWorker()
    yield w
    await w.aclose()


async def _drain(worker: Any, max_rounds: int = 10) -> int:
    ran = 0
    for _ in range(max_rounds):
        if not await worker.process_one():
            break
        ran += 1
    return ran


async def _setup_notebook_with_pdf(
    client: AsyncClient, worker: Any, name: str, pdf_text: str
) -> dict[str, Any]:
    auth = await _login(client, name)
    nb = (
        await client.post(
            "/api/v1/notebooks", json={"title": f"Carnet {name}"},
            cookies=_cookies(auth), headers=_headers(auth),
        )
    ).json()
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/file",
        files={"file": ("manual.pdf", _make_pdf([pdf_text]), "application/pdf")},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201, resp.text
    await _drain(worker)
    detail = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{resp.json()['source']['id']}",
        cookies=_cookies(auth),
    )).json()
    assert detail["status"] == "ready", f"status_detail={detail.get('status_detail')!r}"
    return {"auth": auth, "notebook": nb}


async def test_search_finds_only_own_notebook(
    client: AsyncClient, worker: Any
) -> None:
    a = await _setup_notebook_with_pdf(
        client, worker, f"Search A {uuid.uuid4().hex[:6]}",
        "Fotosinteza este procesul prin care plantele produc glucoza."
    )
    b = await _setup_notebook_with_pdf(
        client, worker, f"Search B {uuid.uuid4().hex[:6]}",
        "Volcanii erupție lava magmă crustă pământ."
    )

    for mode in ("text", "vector", "both"):
        resp = await client.post(
            f"/api/v1/notebooks/{a['notebook']['id']}/search",
            json={"query": "fotosinteza glucoza", "mode": mode},
            cookies=_cookies(a["auth"]),
        )
        assert resp.status_code == 200, f"mode={mode}: {resp.text}"
        results = resp.json()
        assert len(results) >= 1, f"mode={mode}: {results}"
        assert "fotosinteză" in results[0]["text"].lower() or \
            "fotosinteza" in results[0]["text"].lower()

    # B searching for A's topic finds nothing (scope is the notebook's own)
    results_b = (await client.post(
        f"/api/v1/notebooks/{b['notebook']['id']}/search",
        json={"query": "fotosinteza glucoza", "mode": "both"},
        cookies=_cookies(b["auth"]),
    )).json()
    assert results_b == []


async def test_chat_citations_validated_and_isolated(
    client: AsyncClient, worker: Any
) -> None:
    a = await _setup_notebook_with_pdf(
        client, worker, f"Chat A {uuid.uuid4().hex[:6]}",
        "Apa se afla in trei stari: solida, lichida si gazoasa."
    )
    nb_id = a["notebook"]["id"]

    # no eligible sources case is impossible here (source ready+selected);
    # create session and ask
    session = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions", json={"title": "Întrebări"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )).json()
    sid = session["id"]

    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages",
        json={"content": "Ce stari are apa?", "idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assistant_id = body["assistant_message_id"]
    assert body["cited"] >= 1

    # citations endpoint: validated, real locator, authorized source
    cites = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages/{assistant_id}/citations",
        cookies=_cookies(a["auth"]),
    )).json()
    assert len(cites) >= 1
    assert cites[0]["source_removed"] is False
    assert cites[0]["chunk_id"]

    # messages ordered
    messages = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages", cookies=_cookies(a["auth"])
    )).json()
    seqs = [m["seq"] for m in messages]
    assert seqs == sorted(seqs)
    assert [m["role"] for m in messages] == ["user", "assistant"]

    # idempotency: same key + same payload -> replay (same assistant id);
    # same key + different payload -> 409 conflict
    r1 = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages",
        json={"content": "Ce stari are apa?", "idempotency_key": "fixed-key-1"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages",
        json={"content": "Ce stari are apa?", "idempotency_key": "fixed-key-1"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert r2.status_code == 200
    assert r2.json()["assistant_message_id"] == r1.json()["assistant_message_id"]
    assert r2.json().get("replayed") is True
    conflict = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages",
        json={"content": "Altă întrebare?", "idempotency_key": "fixed-key-1"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert conflict.status_code == 409

    # B cannot touch A's session
    auth_b = await _login(client, f"Chat B {uuid.uuid4().hex[:6]}")
    resp = await client.get(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages",
        cookies=_cookies(auth_b), headers=_headers(auth_b),
    )
    assert resp.status_code == 404

    # A13: declared missing information, no invented citations
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages",
        json={"content": "Care e capitala Franței? [fără răspuns]"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert resp.status_code == 200
    ans_id = resp.json()["assistant_message_id"]
    assert resp.json()["cited"] == 0
    cites = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sessions/{sid}/messages/{ans_id}/citations",
        cookies=_cookies(a["auth"]),
    )).json()
    assert cites == []


async def test_context_revision_changes_retrieval_scope(
    client: AsyncClient, worker: Any
) -> None:
    """A17: after removing the source, new questions no longer retrieve it."""
    a = await _setup_notebook_with_pdf(
        client, worker, f"Rev A {uuid.uuid4().hex[:6]}",
        "Gravitatia este forta care atrage corpurile spre suprafata pamantului."
    )
    nb_id = a["notebook"]["id"]
    sources = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sources", cookies=_cookies(a["auth"])
    )).json()
    source_id = sources[0]["id"]

    before = (await client.post(
        f"/api/v1/notebooks/{nb_id}/search",
        json={"query": "gravitatia"}, cookies=_cookies(a["auth"]),
    )).json()
    assert len(before) >= 1

    await client.delete(
        f"/api/v1/notebooks/{nb_id}/sources/{source_id}",
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    after = (await client.post(
        f"/api/v1/notebooks/{nb_id}/search",
        json={"query": "gravitatia"}, cookies=_cookies(a["auth"]),
    )).json()
    assert after == []

    # Asking still works, but without evidence the answer abstains and has no
    # citations; model memory is not used as notebook truth.
    session = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions", json={},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )).json()
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        json={"content": "Ce spune materialul despre gravitație?"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert resp.status_code == 200
    assert resp.json()["cited"] == 0
    messages = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        cookies=_cookies(a["auth"]),
    )).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "Ce spune materialul despre gravitație?"
    assert "dovezi relevante" in messages[1]["content"]


async def test_full_probe_two_users_restart(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    """G2/G3 probe: A/B, upload PDF, process, search, chat/citation,
    isolation, and persistence across an app restart (new app instance)."""
    a = await _setup_notebook_with_pdf(
        client, worker, f"Proba A {uuid.uuid4().hex[:6]}",
        "Republica Moldova are capitala la Chișinău."
    )
    b = await _login(client, f"Proba B {uuid.uuid4().hex[:6]}")

    nb_id = a["notebook"]["id"]
    session = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions", json={},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )).json()
    sent = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        json={"content": "Care este capitala?"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert sent.status_code == 200
    assert sent.json()["cited"] >= 1

    # restart: a brand-new app instance sees the same durable data
    api = pytest.importorskip("api.guguta_app")
    app2 = api.create_guguta_app(_config(guguta_db["api_dsn"]))
    async with AsyncClient(
        transport=ASGITransport(app=app2), base_url="http://localhost:3000"
    ) as client2:
        sessions = (await client2.get(
            f"/api/v1/notebooks/{nb_id}/sessions", cookies=_cookies(a["auth"])
        )).json()
        assert len(sessions) == 1
        messages = (await client2.get(
            f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
            cookies=_cookies(a["auth"]),
        )).json()
        assert len(messages) == 2

        # isolation persists after restart
        resp = await client2.get(
            f"/api/v1/notebooks/{nb_id}/sessions", cookies=_cookies(b)
        )
        assert resp.status_code == 404
