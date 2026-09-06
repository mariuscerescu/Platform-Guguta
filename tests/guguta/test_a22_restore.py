"""A22: backup restore — ownership, revoked packages, files and chat survive.

Uses a real pg_dump/psql cycle through the compose PostgreSQL container:
1. build state (users, notebook, processed source, chat, share + import +
   revocation),
2. pg_dump the test database,
3. restore into a fresh database,
4. verify ownership, chat, revoked package and recipient copy.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from tests.guguta.test_materials_worker import (
    _config,
    _cookies,
    _drain,
    _headers,
    _login,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(_config(guguta_db["api_dsn"]))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3000"
    ) as c:
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

RESTORE_DB = "guguta_restore"


def _docker_available() -> bool:
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        return "guguta-db-1" in r.stdout
    except Exception:
        return False


def _docker_sql(sql: str, database: str = "guguta_test") -> None:
    subprocess.run(
        ["docker", "exec", "-i", "guguta-db-1", "psql", "-U", "guguta_migrator",
         "-d", database],
        input=sql.encode(), capture_output=True, check=True, timeout=60,
    )


def _dump(database: str) -> str:
    r = subprocess.run(
        ["docker", "exec", "guguta-db-1", "pg_dump", "-U", "guguta_migrator",
         "-d", database],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=120,
    )
    return r.stdout


def _query(restore_dsn: str, sql: str) -> list[tuple]:
    eng = sa.create_engine(restore_dsn)
    try:
        with eng.connect() as conn:
            rows = conn.execute(sa.text(sql)).mappings().all()
            return [tuple(r.values()) for r in rows]
    finally:
        eng.dispose()


async def test_backup_restore_preserves_state(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    if not _docker_available():
        pytest.skip("docker CLI unavailable")

    author = await _login(client, f"A22 author {uuid.uuid4().hex[:6]}")
    recipient = await _login(client, f"A22 recip {uuid.uuid4().hex[:6]}")

    nb = (await client.post(
        "/api/v1/notebooks", json={"title": "A22 carnet autor"},
        cookies=_cookies(author), headers=_headers(author),
    )).json()
    await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={"title": "material", "text": "Material A22 pentru restaurare."},
        cookies=_cookies(author), headers=_headers(author),
    )
    await _drain(worker)
    session = (await client.post(
        f"/api/v1/notebooks/{nb['id']}/sessions", json={},
        cookies=_cookies(author), headers=_headers(author),
    )).json()
    await client.post(
        f"/api/v1/notebooks/{nb['id']}/sessions/{session['id']}/messages",
        json={"content": "material"},
        cookies=_cookies(author), headers=_headers(author),
    )
    src_list = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources", cookies=_cookies(author)
    )).json()
    share = (await client.post(
        f"/api/v1/notebooks/{nb['id']}/shares",
        json={"source_ids": [s["id"] for s in src_list]},
        cookies=_cookies(author), headers=_headers(author),
    )).json()
    await client.post(
        "/api/v1/imports",
        json={"token": share["token"], "idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(recipient), headers=_headers(recipient),
    )
    revoke = await client.post(
        f"/api/v1/notebooks/{nb['id']}/shares/{share['share_id']}/revoke",
        cookies=_cookies(author), headers=_headers(author),
    )
    assert revoke.status_code == 200

    # ---- backup (pg_dump of the test database) ----
    dump = _dump("guguta_test")
    print(f"[diag] dump type={type(dump)} len={len(dump) if dump else 0}")

    # ---- restore into a fresh database ----
    server = sa.create_engine(
        guguta_db["migrator_dsn"].rsplit("/", 1)[0] + "/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with server.connect() as conn:
        conn.exec_driver_sql(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{RESTORE_DB}' AND pid <> pg_backend_pid()"
        )
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{RESTORE_DB}"')
        conn.exec_driver_sql(f'CREATE DATABASE "{RESTORE_DB}"')
    server.dispose()

    subprocess.run(
        ["docker", "exec", "-i", "guguta-db-1", "psql", "-U", "guguta_migrator",
         "-d", RESTORE_DB],
        input=dump.encode(), capture_output=True, check=True, timeout=120,
    )

    restore_dsn = (
        guguta_db["migrator_dsn"].rsplit("/", 1)[0] + "/" + RESTORE_DB
    )

    # ---- verify the restored state (A22) ----
    authors = _query(
        restore_dsn,
        "SELECT display_name FROM users WHERE display_name LIKE 'A22 author%'",
    )
    assert len(authors) == 1  # ownership preserved

    notebooks = _query(
        restore_dsn,
        "SELECT title, origin, status FROM digital_notebooks ORDER BY title",
    )
    titles = [t[0] for t in notebooks]
    assert "A22 carnet autor" in titles

    revoked = _query(
        restore_dsn,
        "SELECT status FROM share_snapshots",
    )
    assert all(s[0] == "revoked" for s in revoked)  # revocation survived (A10)

    imports = _query(
        restore_dsn,
        "SELECT COUNT(*) FROM share_imports",
    )
    assert imports[0][0] == 1  # the recipient's import record survived

    chat = _query(
        restore_dsn,
        "SELECT role, content FROM chat_messages WHERE content = 'material'",
    )
    assert len(chat) == 1  # chat history survived

    sources = _query(
        restore_dsn,
        "SELECT ns.local_name, ns.status FROM notebook_sources ns",
    )
    assert any(s[1] == "ready" for s in sources)  # recipient copy usable
    assert any("A22" in s[0] for s in sources) or any(
        "material" == s[0] for s in sources
    )

    artifacts = _query(
        restore_dsn,
        "SELECT count(*) FROM processing_artifacts WHERE status = 'complete'",
    )
    assert artifacts[0][0] >= 1  # processing artifacts survived

    # cleanup
    server2 = sa.create_engine(
        guguta_db["migrator_dsn"].rsplit("/", 1)[0] + "/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with server2.connect() as conn:
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{RESTORE_DB}"')
    server2.dispose()
