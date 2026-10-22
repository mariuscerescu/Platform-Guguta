"""Audit probes: assertions reproduce current defects, NOT acceptance tests.

Run only against a disposable PostgreSQL server: imported fixtures recreate
guguta_test and reset runtime role passwords on the selected server.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.guguta.test_materials_worker import _cookies, _headers, _login
from tests.guguta.test_search_chat import _drain
from tests.guguta.test_search_chat import client as client_fixture
from tests.guguta.test_search_chat import worker as worker_fixture

client = client_fixture
worker = worker_fixture

pytest_plugins = ["tests.guguta.conftest"]
pytestmark = pytest.mark.asyncio


async def test_oidc_redirect_loses_state_cookie():
    from api.routers.guguta_v1 import auth_router
    app = FastAPI()
    app.include_router(auth_router)
    app.state.guguta_config = SimpleNamespace(auth_mode="oidc", public_origin="https://school.example")
    app.state.guguta_oidc = SimpleNamespace(begin_login=lambda codec: ("https://id.example/authorize", "synthetic-state"))
    app.state.guguta_state_codec = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://school.example") as c:
        r = await c.get("/api/v1/auth/oidc/login")
    assert r.status_code == 307
    assert "set-cookie" not in r.headers  # defect reproduced


async def test_production_accepts_mock_and_default_encryption():
    from open_notebook.database.guguta.config import GugutaConfig
    cfg = GugutaConfig(environment="production", auth_mode="oidc",
        database_url_api="synthetic", database_url_worker="synthetic",
        database_url_migrator="synthetic", server_secret="",
        oidc_issuer="http://id.example", oidc_client_id="client", oidc_client_secret="synthetic")
    assert cfg.chat_provider == "mock"
    assert cfg.credential_encryption_keys["k1"].startswith("dev-only")
    assert not cfg.server_secret


async def setup_chat(client, worker):
    auth = await _login(client, "audit-" + uuid.uuid4().hex)
    kw = dict(cookies=_cookies(auth), headers=_headers(auth))
    nb = (await client.post("/api/v1/notebooks", json={"title": "Audit"}, **kw)).json()["id"]
    base = f"/api/v1/notebooks/{nb}"
    sources = []
    for content in ["SECRET_OLD_AUDIT: fotosinteza produce glucoza.", "Planetele se rotesc in jurul Soarelui."]:
        r = await client.post(base + "/sources/text", json={"text": content}, **kw)
        assert r.status_code == 201, r.text
        sources.append(r.json()["source"]["id"])
    await _drain(worker)
    sid = (await client.post(base + "/sessions", json={}, **kw)).json()["id"]
    return kw, base, sid, sources


async def test_removed_source_history_still_sent(client, worker):
    from open_notebook.ai.guguta.chat import ChatAnswer
    kw, base, sid, sources = await setup_chat(client, worker)
    seen = []
    class Probe:
        model_name = "audit"
        def generate(self, question, context_chunks, history):
            seen.append(history)
            return ChatAnswer("SECRET_OLD_AUDIT", [], "audit")
    client._transport.app.state.guguta_chat._provider = Probe()
    route = base + f"/sessions/{sid}/messages"
    assert (await client.post(route, json={"content": "fotosinteza"}, **kw)).status_code < 300
    assert (await client.delete(base + "/sources/" + sources[0], **kw)).status_code == 200
    assert (await client.post(route, json={"content": "planetele"}, **kw)).status_code < 300
    assert any("SECRET_OLD_AUDIT" in m["content"] for m in seen[-1])


async def test_provider_failure_leaves_retry_pending(client, worker):
    kw, base, sid, _ = await setup_chat(client, worker)
    class Broken:
        model_name = "audit"
        def generate(self, *args):
            raise RuntimeError("synthetic failure")
    client._transport.app.state.guguta_chat._provider = Broken()
    route = base + f"/sessions/{sid}/messages"
    payload = {"content": "planetele", "idempotency_key": uuid.uuid4().hex}
    assert (await client.post(route, json=payload, **kw)).status_code == 502
    retry = await client.post(route, json=payload, **kw)
    assert retry.json()["pending"] is True


async def test_stale_worker_publishes_before_fencing(client, worker):
    from open_notebook.database.guguta.engine import system_connection
    from open_notebook.jobs.guguta.handlers import process_material_version
    from open_notebook.jobs.guguta.queue import claim
    auth = await _login(client, "audit-worker-" + uuid.uuid4().hex)
    kw = dict(cookies=_cookies(auth), headers=_headers(auth))
    nb = (await client.post("/api/v1/notebooks", json={"title": "Worker"}, **kw)).json()["id"]
    base = f"/api/v1/notebooks/{nb}"
    r = await client.post(base + "/sources/text", json={"text": "Audit material pentru procesare."}, **kw)
    source_id = r.json()["source"]["id"]
    job = await claim(worker._engine)
    assert job is not None
    async with system_connection(worker._engine) as conn:
        await conn.execute(text("UPDATE processing_jobs SET lease_token='replacement-worker-token' WHERE id=:id"), {"id": job.id})
    await process_material_version(worker._engine, worker._storage, worker._provider, job)
    detail = await client.get(base + "/sources/" + source_id, **kw)
    assert detail.json()["status"] == "ready"  # lost lease still publishes
