"""Real dump/restore and incremental migration on the audit-only container.

Requires Docker CLI access. Explicitly refuses any other database server.
No application volumes, existing databases or runtime services are touched.
"""
import asyncio
import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from test_backend_audit import env as env_fixture
from test_backend_audit import login, notebook

from api.guguta_app import create_guguta_app
from tests.guguta.test_materials_worker import _make_pdf

env = env_fixture

pytest_plugins=["tests.guguta.conftest"]
pytestmark=pytest.mark.asyncio
CONTAINER="guguta-backend-audit-20260906"


def guarded_server(env):
    url=sa.make_url(env.dsns["migrator_dsn"])
    assert url.host=="127.0.0.1" and url.port==55434
    return sa.create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT")


async def test_restore_database_files_and_authorization(env,tmp_path):
    server=guarded_server(env)
    target="guguta_backend_restore_"+uuid.uuid4().hex[:8]
    author,_=await login(env)
    nb=await notebook(env,author)
    payload=_make_pdf(["Planetele se rotesc in jurul soarelui. Material pentru backup."])
    r=await env.client.post(f"/api/v1/notebooks/{nb}/sources/file",headers=author,files={"file":("manual.pdf",payload,"application/pdf")})
    assert r.status_code==201
    sid=r.json()["source"]["id"]
    assert await env.worker.process_one()
    session=(await env.client.post(f"/api/v1/notebooks/{nb}/sessions",headers=author,json={})).json()["id"]
    response=await env.client.post(f"/api/v1/notebooks/{nb}/sessions/{session}/messages",headers=author,json={"content":"Planetele"})
    assert response.status_code==200
    share=(await env.client.post(f"/api/v1/notebooks/{nb}/shares",headers=author,json={"source_ids":[sid]})).json()
    recipient,_=await login(env)
    key=uuid.uuid4().hex
    copied=await env.client.post("/api/v1/imports",headers=recipient,json={"token":share["token"],"idempotency_key":key})
    assert copied.status_code==201
    copied_nb=copied.json()["notebook_id"]
    revoke=await env.client.post(f"/api/v1/notebooks/{nb}/shares/{share['share_id']}/revoke",headers=author)
    assert revoke.status_code==200
    # Quiescent synthetic workload, then independent copy of private bytes.
    backup_root=tmp_path/"backup-storage"
    restore_root=tmp_path/"restored-storage"
    shutil.copytree(env.cfg.storage_root,backup_root)
    dump=subprocess.run(["docker","exec",CONTAINER,"pg_dump","-U","guguta_migrator","-d","guguta_test"],capture_output=True,check=True,timeout=40).stdout
    with server.connect() as c:
        c.exec_driver_sql(f'CREATE DATABASE "{target}"')
    restored_app=None
    try:
        subprocess.run(["docker","exec","-i",CONTAINER,"psql","-v","ON_ERROR_STOP=1","-U","guguta_migrator","-d",target],input=dump,capture_output=True,check=True,timeout=40)
        shutil.copytree(backup_root,restore_root)
        cfg=env.cfg.model_copy(update={
            "database_url_api":sa.make_url(env.dsns["api_dsn"]).set(database=target).render_as_string(hide_password=False),
            "storage_root":str(restore_root),
        })
        restored_app=create_guguta_app(cfg)
        async with AsyncClient(transport=ASGITransport(app=restored_app),base_url="http://localhost:3000") as client:
            sources=(await client.get(f"/api/v1/notebooks/{copied_nb}/sources",headers=recipient)).json()
            download=await client.get(f"/api/v1/notebooks/{copied_nb}/sources/{sources[0]['id']}/download",headers=recipient)
            assert download.status_code==200
            assert hashlib.sha256(download.content).digest()==hashlib.sha256(payload).digest()
            assert (await client.get(f"/api/v1/notebooks/{nb}",headers=recipient)).status_code==404
            history=(await client.get(f"/api/v1/notebooks/{nb}/sessions/{session}/messages",headers=author)).json()
            assert len(history)==2
            assert (await client.post("/api/v1/imports",headers=recipient,json={"token":share["token"],"idempotency_key":uuid.uuid4().hex})).status_code==409
            replay=await client.post("/api/v1/imports",headers=recipient,json={"token":share["token"],"idempotency_key":key})
            assert replay.json()["notebook_id"]==copied_nb
    finally:
        if restored_app:
            await restored_app.state.guguta_engine.dispose()
        with server.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE "{target}" WITH (FORCE)')
        server.dispose()


async def test_upgrade_0008_to_0009_preserves_existing_rows(env):
    server=guarded_server(env)
    target="guguta_backend_upgrade_"+uuid.uuid4().hex[:8]
    url=sa.make_url(env.dsns["migrator_dsn"]).set(database=target)
    with server.connect() as c:
        c.exec_driver_sql(f'CREATE DATABASE "{target}"')
    engine=sa.create_engine(url)
    task_env=os.environ.copy()
    task_env["GUGUTA_DATABASE_URL_MIGRATOR"]=url.render_as_string(hide_password=False)
    python=str(Path(".venv/Scripts/python.exe").resolve())
    def upgrade(revision):
        subprocess.run([python,"-m","alembic","upgrade",revision],env=task_env,capture_output=True,check=True,timeout=40)
    try:
        await asyncio.to_thread(upgrade,"0008")
        with engine.begin() as c:
            user=c.execute(sa.text("SELECT guguta_provision_user('upgrade-audit','subject','Synthetic')")).scalar_one()
            nb=uuid.uuid4()
            c.execute(sa.text("INSERT INTO digital_notebooks(id,owner_id,title) VALUES(:n,:u,'Preserved')"),{"n":nb,"u":user})
        await asyncio.to_thread(upgrade,"head")
        with engine.connect() as c:
            assert c.execute(sa.text("SELECT version_num FROM guguta_alembic")).scalar_one()=="0009"
            assert c.execute(sa.text("SELECT title FROM digital_notebooks WHERE id=:id"),{"id":nb}).scalar_one()=="Preserved"
            assert c.execute(sa.text("SELECT to_regprocedure('guguta_share_lock(uuid)') IS NOT NULL")).scalar_one()
    finally:
        engine.dispose()
        with server.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE "{target}" WITH (FORCE)')
        server.dispose()
