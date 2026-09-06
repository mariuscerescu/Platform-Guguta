"""Independent backend acceptance probes. Failing assertions expose defects.

ONLY a disposable PostgreSQL server: tests.guguta.conftest recreates guguta_test
and changes runtime-role passwords. No production application code is patched
on disk; monkeypatches below simulate concurrency/faults in this test process.
"""
import asyncio
import hashlib
import io
import os
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from api.guguta_app import create_guguta_app
from open_notebook.ai.guguta.chat import ChatAnswer
from open_notebook.database.guguta.engine import actor_connection, system_connection
from open_notebook.jobs.guguta.queue import claim, enqueue
from open_notebook.jobs.guguta.worker import Worker
from tests.guguta.test_materials_worker import _config, _make_pdf

pytest_plugins = ["tests.guguta.conftest"]
pytestmark = pytest.mark.asyncio

# Refuse collection before the destructive upstream fixture can run elsewhere.
_audit_url = sa.make_url(os.environ.get("GUGUTA_TEST_DATABASE_URL", "postgresql://invalid"))
if (_audit_url.host, _audit_url.port) != ("127.0.0.1", 55434):
    raise RuntimeError("Audit requires its disposable PostgreSQL at 127.0.0.1:55434")


@pytest_asyncio.fixture
async def env(guguta_db, tmp_path):
    db = sa.create_engine(guguta_db["migrator_dsn"])
    with db.begin() as conn:
        conn.execute(sa.text("UPDATE processing_jobs SET status='cancelled' WHERE status IN ('queued','running','claimed')"))
    cfg = _config(guguta_db["api_dsn"]).model_copy(update={
        "database_url_worker": guguta_db["worker_dsn"],
        "storage_root": str(tmp_path / "storage"),
    })
    app = create_guguta_app(cfg)
    worker = Worker(cfg)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://localhost:3000") as client:
        yield SimpleNamespace(app=app, worker=worker, client=client, db=db, cfg=cfg, dsns=guguta_db)
    await worker.aclose()
    await app.state.guguta_engine.dispose()
    db.dispose()


async def login(e, role=None):
    e.client.cookies.clear()
    r = await e.client.post("/api/v1/auth/dev-login", json={"display_name": "audit-" + uuid.uuid4().hex})
    assert r.status_code == 200
    headers = {"Cookie": "guguta_session=" + r.cookies["guguta_session"],
               "X-Guguta-CSRF": r.headers["X-Guguta-CSRF"], "Origin": "http://localhost:3000"}
    if role:
        with e.db.begin() as conn:
            conn.execute(sa.text("UPDATE users SET roles=ARRAY['user',:r]::varchar[] WHERE id=:id"), {"r": role, "id": uuid.UUID(r.json()["id"])})
    return headers, r.json()["id"]


async def notebook(e, headers):
    r = await e.client.post("/api/v1/notebooks", headers=headers, json={"title": "Audit carnet"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def source(e, h, nb, content="Audit material despre plante si fotosinteza.", process=True):
    r = await e.client.post(f"/api/v1/notebooks/{nb}/sources/text", headers=h, json={"text": content, "title": "Audit material"})
    assert r.status_code == 201, r.text
    if process:
        assert await e.worker.process_one()
    return r.json()["source"]["id"]


async def chat_setup(e):
    h, uid = await login(e)
    nb = await notebook(e, h)
    sid = await source(e, h, nb)
    r = await e.client.post(f"/api/v1/notebooks/{nb}/sessions", headers=h, json={})
    assert r.status_code == 201
    return h, uid, nb, sid, r.json()["id"]


async def test_timestamps_advance_between_inserts(env):
    h, _ = await login(env)
    n1 = await notebook(env, h)
    await asyncio.sleep(0.05)
    n2 = await notebook(env, h)
    with env.db.connect() as c:
        times = [c.execute(sa.text("SELECT created_at FROM digital_notebooks WHERE id=:id"), {"id": uuid.UUID(n)}).scalar_one() for n in (n1,n2)]
        default = c.execute(sa.text("SELECT column_default FROM information_schema.columns WHERE table_name='digital_notebooks' AND column_name='created_at'")).scalar_one()
    assert times[1] > times[0], f"timestamps identical; DB default={default}"


async def test_worker_cannot_mint_admin_http_session(env):
    _, uid = await login(env, "admin")
    token = "synthetic-audit-token-" + uuid.uuid4().hex
    denied = False
    try:
        async with system_connection(env.worker._engine) as c:
            await c.execute(sa.text("SELECT guguta_create_session(:u,:h,interval '10 minutes')"),
                {"u": uuid.UUID(uid), "h": hashlib.sha256(token.encode()).hexdigest()})
    except sa.exc.DBAPIError:
        denied = True
    if denied:
        return
    r = await env.client.get("/api/v1/auth/me", headers={"Cookie": "guguta_session=" + token})
    assert r.status_code == 401, "worker DB role minted an HTTP session for synthetic admin"


async def test_source_patch_enforces_parent_notebook(env):
    h, _ = await login(env)
    a, b = await notebook(env,h), await notebook(env,h)
    sid = await source(env,h,a)
    r = await env.client.patch(f"/api/v1/notebooks/{b}/sources/{sid}", headers=h, json={"selected_for_chat": False})
    assert r.status_code == 404, f"wrong notebook accepted: {r.status_code}"


async def test_note_patch_enforces_parent_notebook(env):
    h, _ = await login(env)
    a,b = await notebook(env,h), await notebook(env,h)
    n = await env.client.post(f"/api/v1/notebooks/{a}/notes", headers=h, json={"title":"Note", "content":"Private"})
    r = await env.client.patch(f"/api/v1/notebooks/{b}/notes/{n.json()['id']}", headers=h, json={"content":"Updated"})
    assert r.status_code == 404, f"wrong notebook accepted: {r.status_code}"


async def test_queue_respects_per_user_cap(env):
    h,_ = await login(env)
    nb = await notebook(env,h)
    for i in range(3):
        await source(env,h,nb,process=False)
    assert await claim(env.worker._engine, max_concurrent_per_user=2)
    assert await claim(env.worker._engine, max_concurrent_per_user=2)
    third = await claim(env.worker._engine, max_concurrent_per_user=2)
    assert third is None, "third queued job claimed despite cap=2"


async def test_claim_does_not_fail_active_last_attempt(env):
    h,_ = await login(env)
    nb=await notebook(env,h)
    await source(env,h,nb,process=False)
    with env.db.begin() as c:
        c.execute(sa.text("UPDATE processing_jobs SET max_attempts=1 WHERE status='queued'"))
    first = await claim(env.worker._engine)
    assert first
    await claim(env.worker._engine)
    with env.db.connect() as c:
        state=c.execute(sa.text("SELECT status FROM processing_jobs WHERE id=:id"), {"id":first.id}).scalar_one()
    assert state == "running", f"valid last attempt marked {state} by another claim"


async def test_worker_publication_atomic_if_outer_transaction_fails(env, monkeypatch):
    from open_notebook.jobs.guguta import handlers
    h,_=await login(env)
    nb=await notebook(env,h)
    sid=await source(env,h,nb,process=False)
    job=await claim(env.worker._engine)
    assert job
    real_system=handlers.system_connection
    @asynccontextmanager
    async def fail_outer_commit(engine):
        async with real_system(engine) as conn:
            yield conn
            raise RuntimeError("AUDIT synthetic outer commit failure")
    monkeypatch.setattr(handlers,"system_connection",fail_outer_commit)
    await handlers.process_material_version(env.worker._engine,env.worker._storage,env.worker._provider,job)
    with env.db.connect() as c:
        state=c.execute(sa.text("SELECT status FROM processing_jobs WHERE id=:id"),{"id":job.id}).scalar_one()
        published=c.execute(sa.text("SELECT count(*) FROM processing_artifacts WHERE material_version_id=:id"),{"id":job.target_id}).scalar_one()
    assert state == "succeeded" or published == 0, f"job={state}, published artifacts={published}"


async def test_truncated_embeddings_cannot_publish_ready(env):
    h,_=await login(env)
    nb=await notebook(env,h)
    sid=await source(env,h,nb,process=False)
    class Empty:
        model_name="guguta-hash-mock"
        model_revision="v1"
        dimension=8
        def embed(self, texts): return []
    env.worker._provider=Empty()
    await env.worker.process_one()
    r=await env.client.get(f"/api/v1/notebooks/{nb}/sources/{sid}",headers=h)
    assert r.json()["status"] != "ready", "ready source with zero embeddings/chunks"


async def test_final_provider_failure_marks_source_error(env):
    h,_=await login(env)
    nb=await notebook(env,h)
    sid=await source(env,h,nb,process=False)
    with env.db.begin() as c:
        c.execute(sa.text("UPDATE processing_jobs SET max_attempts=1 WHERE status='queued'"))
    class Broken:
        def embed(self, texts): raise RuntimeError("synthetic provider unavailable")
    env.worker._provider=Broken()
    await env.worker.process_one()
    r=await env.client.get(f"/api/v1/notebooks/{nb}/sources/{sid}",headers=h)
    assert r.json()["status"] == "error", f"terminal job failure leaves source={r.json()['status']}"


async def test_cancelled_generation_not_exposed_as_answer(env):
    h,uid,nb,sid,session=await chat_setup(env)
    class ChangingProvider:
        model_name="audit"
        def generate(self,*args):
            with env.db.begin() as c:
                c.execute(sa.text("UPDATE digital_notebooks SET context_revision=context_revision+1 WHERE id=:id"),{"id":uuid.UUID(nb)})
            return ChatAnswer("STALE_AUDIT_ANSWER",[],"audit")
    env.app.state.guguta_chat._provider=ChangingProvider()
    path=f"/api/v1/notebooks/{nb}/sessions/{session}/messages"
    r=await env.client.post(path,headers=h,json={"content":"plante"})
    assert r.status_code == 200, r.text
    assert r.json().get("cancelled") is True
    history=(await env.client.get(path,headers=h)).json()
    assert all(m["content"] != "STALE_AUDIT_ANSWER" for m in history), "cancelled answer still exposed by GET messages"


async def test_import_same_key_concurrent_replays(env,monkeypatch):
    h,_=await login(env)
    nb=await notebook(env,h)
    sid=await source(env,h,nb)
    share=await env.client.post(f"/api/v1/notebooks/{nb}/shares",headers=h,json={"source_ids":[sid]})
    receiver,_=await login(env)
    service=env.app.state.guguta_sharing
    original=service._idempotent_lookup
    barrier=asyncio.Event()
    arrived=0
    async def synchronized(*args):
        nonlocal arrived
        value=await original(*args)
        arrived+=1
        if arrived==2: barrier.set()
        await asyncio.wait_for(barrier.wait(),3)
        return value
    monkeypatch.setattr(service,"_idempotent_lookup",synchronized)
    body={"token":share.json()["token"],"idempotency_key":uuid.uuid4().hex}
    responses=await asyncio.wait_for(asyncio.gather(*[
        env.client.post("/api/v1/imports",headers=receiver,json=body) for _ in range(2)
    ]),10)
    assert [r.status_code for r in responses] == [201,201], f"statuses={[r.status_code for r in responses]}"
    assert responses[0].json()["notebook_id"] == responses[1].json()["notebook_id"]


async def test_same_email_distinct_oidc_subjects_can_provision(env):
    email="audit-"+uuid.uuid4().hex+"@example.test"
    with env.db.begin() as c:
        c.execute(sa.text("SELECT guguta_provision_user('issuer-A',:s,'One',:e)"),{"s":uuid.uuid4().hex,"e":email})
    error=None
    try:
        with env.db.begin() as c:
            c.execute(sa.text("SELECT guguta_provision_user('issuer-B',:s,'Two',:e)"),{"s":uuid.uuid4().hex,"e":email})
    except sa.exc.IntegrityError as exc:
        error=type(exc.orig).__name__
    assert error is None, f"distinct issuer/subject rejected on email: {error}"


@pytest.mark.parametrize("missing",["exp","iss","aud"])
async def test_oidc_required_claim_is_mandatory(missing):
    from authlib.jose import JsonWebToken
    from cryptography.hazmat.primitives.asymmetric import rsa
    from open_notebook.auth.guguta.oidc import OidcClient, OidcConfig, OidcError
    from tests.guguta.test_oidc_http_f01 import _int_b64
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pub=key.public_key().public_numbers()
    jwks={"keys":[{"kty":"RSA","n":_int_b64(pub.n),"e":_int_b64(pub.e),"kid":"audit","alg":"RS256"}]}
    claims={"iss":"https://issuer.test","aud":"client","exp":int(time.time())+600,"iat":int(time.time()),"nonce":"audit","sub":"synthetic"}
    claims.pop(missing)
    token=JsonWebToken(["RS256"]).encode({"alg":"RS256","kid":"audit"},claims,key).decode()
    oidc=OidcClient(OidcConfig(issuer="https://issuer.test",client_id="client",client_secret="synthetic",redirect_uri="https://school.test/callback"))
    try:
        with pytest.raises(OidcError):
            oidc._validate_id_token(token,jwks,"audit")
    finally:
        await oidc.aclose()


async def test_oidc_real_routes_with_isolated_dsn(env):
    from tests.guguta import test_oidc_http_f01 as t
    from open_notebook.auth.guguta.oidc import OidcClient,OidcConfig
    cfg=t._oidc_config().model_copy(update={"database_url_api":env.dsns["api_dsn"]})
    app=create_guguta_app(cfg)
    await app.state.guguta_oidc.aclose()
    http,issued=t._fake_oidc_transport()
    app.state.guguta_oidc=OidcClient(OidcConfig(issuer=t.ISSUER,client_id="guguta-dev",client_secret="s",redirect_uri=cfg.oidc_redirect_uri),http=http)
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://localhost:3001") as c:
            await t.test_oidc_full_http_flow_f01((c,issued))
    finally:
        await http.aclose()
        await app.state.guguta_engine.dispose()


async def test_cross_user_download_and_notes_denied(env):
    h,_=await login(env)
    nb=await notebook(env,h)
    sid=await source(env,h,nb)
    note=await env.client.post(f"/api/v1/notebooks/{nb}/notes",headers=h,json={"title":"private","content":"private"})
    foreign,_=await login(env)
    cases=[("GET",f"/api/v1/notebooks/{nb}/sources/{sid}/download",None),
        ("PATCH",f"/api/v1/notebooks/{nb}/notes/{note.json()['id']}",{"content":"changed"})]
    for method,path,body in cases:
        r=await env.client.request(method,path,headers=foreign,json=body)
        assert r.status_code==404, (method,r.status_code)


async def test_malformed_template_item_returns_validation_error(env):
    h,_=await login(env,"catalog_editor")
    tpl=await env.client.post("/api/v1/admin/catalog/templates",headers=h,json={"slug":uuid.uuid4().hex,"title":"Audit"})
    r=await env.client.post(f"/api/v1/admin/catalog/templates/{tpl.json()['id']}/versions",headers=h,
        json={"items":[{"material_version_id":str(uuid.uuid4()),"display_name":123}]})
    assert r.status_code==422, f"invalid display_name returned {r.status_code}"


async def test_pdf_romanian_filename_roundtrip(env):
    h,_=await login(env)
    nb=await notebook(env,h)
    payload=_make_pdf(["Audit PDF roundtrip with authorized private download."])
    r=await env.client.post(f"/api/v1/notebooks/{nb}/sources/file",headers=h,files={"file":("Științe.pdf",payload,"application/pdf")})
    assert r.status_code==201,r.text
    await env.worker.process_one()
    download=await env.client.get(f"/api/v1/notebooks/{nb}/sources/{r.json()['source']['id']}/download",headers=h)
    assert download.status_code==200
    assert download.content==payload
    assert "filename*=UTF-8''" in download.headers["content-disposition"]


async def test_history_exclusion_same_session_after_source_change(env):
    h,uid,nb,sid,session=await chat_setup(env)
    path=f"/api/v1/notebooks/{nb}/sessions/{session}/messages"
    class Old:
        model_name="audit"
        def generate(self,*args):return ChatAnswer("OLD_PRIVATE_ANSWER",[],"audit")
    env.app.state.guguta_chat._provider=Old()
    assert (await env.client.post(path,headers=h,json={"content":"plante"})).status_code==200
    assert (await env.client.delete(f"/api/v1/notebooks/{nb}/sources/{sid}",headers=h)).status_code==200
    await source(env,h,nb,"Planetele graviteaza in jurul Soarelui.")
    captured=[]
    class Capture:
        model_name="audit"
        def generate(self,q,chunks,history):
            captured.extend(history)
            return ChatAnswer("NEW_ANSWER",[],"audit")
    env.app.state.guguta_chat._provider=Capture()
    assert (await env.client.post(path,headers=h,json={"content":"Planetele"})).status_code==200
    assert all("OLD_PRIVATE_ANSWER" not in m["content"] for m in captured)


async def test_chat_works_with_one_connection_pool(env):
    h,uid,nb,sid,session=await chat_setup(env)
    cfg=env.cfg.model_copy(update={"db_pool_size":1,"db_max_overflow":0,"db_pool_timeout_seconds":1})
    app=create_guguta_app(cfg)
    try:
        async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=False),base_url="http://localhost:3000") as c:
            r=await asyncio.wait_for(c.post(f"/api/v1/notebooks/{nb}/sessions/{session}/messages",headers=h,json={"content":"plante"}),5)
            assert r.status_code==200,f"nested pool checkout: HTTP {r.status_code}"
    finally:
        await app.state.guguta_engine.dispose()


async def test_auth_mode_uses_actual_app_config(env):
    from tests.guguta.test_oidc_http_f01 import _oidc_config
    cfg=_oidc_config().model_copy(update={"database_url_api":env.dsns["api_dsn"]})
    app=create_guguta_app(cfg)
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://localhost:3000") as c:
            r=await c.get("/api/v1/auth/config")
            assert r.json()["auth_mode"]=="oidc", "discovery disagrees with configured app"
    finally:
        await app.state.guguta_oidc.aclose()
        await app.state.guguta_engine.dispose()


async def test_upload_rejects_nul_as_client_error(env):
    h,_=await login(env)
    nb=await notebook(env,h)
    r=await env.client.post(f"/api/v1/notebooks/{nb}/sources/text",headers=h,json={"text":"test\u0000document"})
    assert r.status_code==422,f"invalid PostgreSQL text returned {r.status_code}"
