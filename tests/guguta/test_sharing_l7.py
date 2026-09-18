"""L7 tests: share snapshots, import, revocation, ordering, A07-A10/A15/A28."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.guguta.test_materials_worker import _config, _drain, _headers, _login

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


def _cookies(auth: dict[str, str]) -> dict[str, str]:
    return {"guguta_session": auth["cookie"]}


async def _author_with_package(client: AsyncClient, worker: Any) -> dict[str, Any]:
    """Author notebook: two sources (one shared), one chat message, one note."""
    author = await _login(client, f"Author {uuid.uuid4().hex[:6]}")
    nb = (
        await client.post(
            "/api/v1/notebooks",
            json={"title": "Carnet de partajat"},
            cookies=_cookies(author),
            headers=_headers(author),
        )
    ).json()
    shared_src = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={
            "title": "Material partajat",
            "text": "Materia partajată vorbește despre fotosinteza plantelor.",
        },
        cookies=_cookies(author),
        headers=_headers(author),
    )
    private_src = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={
            "title": "Material privat",
            "text": "Materialul privat conține notițele personale ale autorului.",
        },
        cookies=_cookies(author),
        headers=_headers(author),
    )
    await _drain(worker)
    session = (
        await client.post(
            f"/api/v1/notebooks/{nb['id']}/sessions",
            json={},
            cookies=_cookies(author),
            headers=_headers(author),
        )
    ).json()
    await client.post(
        f"/api/v1/notebooks/{nb['id']}/sessions/{session['id']}/messages",
        json={"content": "fotosinteza plantelor"},
        cookies=_cookies(author),
        headers=_headers(author),
    )
    await client.post(
        f"/api/v1/notebooks/{nb['id']}/notes",
        json={"title": "Notiță privată", "content": "Doar pentru autor."},
        cookies=_cookies(author),
        headers=_headers(author),
    )
    share = (
        await client.post(
            f"/api/v1/notebooks/{nb['id']}/shares",
            json={
                "source_ids": [shared_src.json()["source"]["id"]],
                "title": "Pachet fotosinteză",
            },
            cookies=_cookies(author),
            headers=_headers(author),
        )
    ).json()
    assert share["material_count"] == 1
    return {
        "author": author,
        "nb": nb,
        "share": share,
        "private_src_id": private_src.json()["source"]["id"],
        "session_id": session["id"],
    }


async def test_share_import_via_link_and_code_a07_a08(
    client: AsyncClient, worker: Any
) -> None:
    pkg = await _author_with_package(client, worker)
    recipient = await _login(client, f"Recipient {uuid.uuid4().hex[:6]}")

    # preview shows ONLY the shared material (A07 allowlist)
    preview_resp = await client.post(
        "/api/v1/imports/preview",
        json={
            "token": f"https://tineri.math.md/edu-platform/import#token={pkg['share']['token']}"
        },
        cookies=_cookies(recipient),
    )
    assert preview_resp.status_code == 200, preview_resp.text
    preview = preview_resp.json()
    assert preview["material_count"] == 1
    assert preview["materials"] == ["Material partajat"]

    # import via link token
    imp1 = await client.post(
        "/api/v1/imports",
        json={"token": pkg["share"]["token"], "idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(recipient),
        headers=_headers(recipient),
    )
    assert imp1.status_code == 201, imp1.text
    nb1 = imp1.json()

    # import via the code reaches the SAME package (A08)
    imp2 = await client.post(
        "/api/v1/imports",
        json={
            "token": f"{pkg['share']['code'][:4]}-{pkg['share']['code'][4:]}".lower(),
            "idempotency_key": uuid.uuid4().hex,
        },
        cookies=_cookies(recipient),
        headers=_headers(recipient),
    )
    assert imp2.status_code == 201, imp2.text
    nb2 = imp2.json()
    assert nb2["notebook_id"] != nb1["notebook_id"]

    for nb_id in (nb1["notebook_id"], nb2["notebook_id"]):
        sources = (
            await client.get(
                f"/api/v1/notebooks/{nb_id}/sources", cookies=_cookies(recipient)
            )
        ).json()
        assert len(sources) == 1
        assert sources[0]["status"] == "ready"
        assert (
            "fotosinteză" in sources[0]["local_name"].lower()
            or sources[0]["local_name"] == "Material partajat"
        )
        # zero personal activity in the copy (A07)
        notes = (
            await client.get(
                f"/api/v1/notebooks/{nb_id}/notes", cookies=_cookies(recipient)
            )
        ).json()
        sessions = (
            await client.get(
                f"/api/v1/notebooks/{nb_id}/sessions", cookies=_cookies(recipient)
            )
        ).json()
        assert notes == [] and sessions == []
        # the copied material is searchable for the recipient
        results = (
            await client.post(
                f"/api/v1/notebooks/{nb_id}/search",
                json={"query": "fotosinteza", "mode": "text"},
                cookies=_cookies(recipient),
            )
        ).json()
        assert len(results) >= 1


async def test_snapshot_pins_versions_a09_a21(client: AsyncClient, worker: Any) -> None:
    pkg = await _author_with_package(client, worker)
    recipient = await _login(client, f"Pin {uuid.uuid4().hex[:6]}")
    imported = (
        await client.post(
            "/api/v1/imports",
            json={"token": pkg["share"]["token"], "idempotency_key": uuid.uuid4().hex},
            cookies=_cookies(recipient),
            headers=_headers(recipient),
        )
    ).json()

    # author replaces the shared source afterwards (delete + new upload)
    src_list = (
        await client.get(
            f"/api/v1/notebooks/{pkg['nb']['id']}/sources",
            cookies=_cookies(pkg["author"]),
        )
    ).json()
    old_src = [s for s in src_list if s["local_name"] == "Material partajat"][0]
    del_src = await client.delete(
        f"/api/v1/notebooks/{pkg['nb']['id']}/sources/{old_src['id']}",
        cookies=_cookies(pkg["author"]),
        headers=_headers(pkg["author"]),
    )
    assert del_src.status_code == 200 and del_src.json()["deleted"] is True, (
        del_src.text
    )
    reup = await client.post(
        f"/api/v1/notebooks/{pkg['nb']['id']}/sources/text",
        json={"title": "Material partajat", "text": "Versiune nouă complet diferită."},
        cookies=_cookies(pkg["author"]),
        headers=_headers(pkg["author"]),
    )
    assert reup.status_code == 201, reup.text
    await _drain(worker)

    # the recipient copy is unchanged (still the pinned version)
    sources = (
        await client.get(
            f"/api/v1/notebooks/{imported['notebook_id']}/sources",
            cookies=_cookies(recipient),
        )
    ).json()
    assert len(sources) == 1
    assert sources[0]["material_version_id"] != "" and sources[0]["status"] == "ready"
    results = (
        await client.post(
            f"/api/v1/notebooks/{imported['notebook_id']}/search",
            json={"query": "fotosinteza", "mode": "text"},
            cookies=_cookies(recipient),
        )
    ).json()
    assert len(results) >= 1  # the OLD pinned version is still theirs


async def test_revoke_blocks_new_imports_keeps_copies_a10(
    client: AsyncClient, worker: Any
) -> None:
    pkg = await _author_with_package(client, worker)
    recipient = await _login(client, f"Rev {uuid.uuid4().hex[:6]}")
    imported = (
        await client.post(
            "/api/v1/imports",
            json={"token": pkg["share"]["token"], "idempotency_key": uuid.uuid4().hex},
            cookies=_cookies(recipient),
            headers=_headers(recipient),
        )
    ).json()

    revoked = await client.post(
        f"/api/v1/notebooks/{pkg['nb']['id']}/shares/{pkg['share']['share_id']}/revoke",
        cookies=_cookies(pkg["author"]),
        headers=_headers(pkg["author"]),
    )
    assert revoked.status_code == 200

    # preview and new imports are refused
    preview = await client.post(
        "/api/v1/imports/preview",
        json={"token": pkg["share"]["token"]},
        cookies=_cookies(recipient),
    )
    assert preview.status_code == 404
    new_import = await client.post(
        "/api/v1/imports",
        json={"token": pkg["share"]["code"], "idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(recipient),
        headers=_headers(recipient),
    )
    assert new_import.status_code == 409
    assert new_import.json()["code"] == "share_revoked"

    # the existing copy remains fully usable
    results = (
        await client.post(
            f"/api/v1/notebooks/{imported['notebook_id']}/search",
            json={"query": "fotosinteza", "mode": "text"},
            cookies=_cookies(recipient),
        )
    ).json()
    assert len(results) >= 1


async def test_expired_share_code_is_rejected(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    import sqlalchemy as sa

    pkg = await _author_with_package(client, worker)
    engine = sa.create_engine(guguta_db["migrator_dsn"])
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE share_snapshots SET expires_at=now()-interval '1 minute' WHERE id=:id"
            ),
            {"id": uuid.UUID(pkg["share"]["share_id"])},
        )
    engine.dispose()
    recipient = await _login(client, f"Expired {uuid.uuid4().hex[:6]}")
    preview = await client.post(
        "/api/v1/imports/preview",
        json={"token": pkg["share"]["code"]},
        cookies=_cookies(recipient),
    )
    assert preview.status_code == 410
    assert preview.json()["code"] == "share_expired"


async def test_replay_after_revocation_r36(client: AsyncClient, worker: Any) -> None:
    pkg = await _author_with_package(client, worker)
    recipient = await _login(client, f"Replay {uuid.uuid4().hex[:6]}")
    key = uuid.uuid4().hex
    first = (
        await client.post(
            "/api/v1/imports",
            json={"token": pkg["share"]["token"], "idempotency_key": key},
            cookies=_cookies(recipient),
            headers=_headers(recipient),
        )
    ).json()

    await client.post(
        f"/api/v1/notebooks/{pkg['nb']['id']}/shares/{pkg['share']['share_id']}/revoke",
        cookies=_cookies(pkg["author"]),
        headers=_headers(pkg["author"]),
    )
    # retry after timeout with the SAME key returns the recipient's own copy
    retry = (
        await client.post(
            "/api/v1/imports",
            json={"token": pkg["share"]["token"], "idempotency_key": key},
            cookies=_cookies(recipient),
            headers=_headers(recipient),
        )
    ).json()
    assert retry.get("replayed") is True
    assert retry["notebook_id"] == first["notebook_id"]


async def test_author_notebook_deletion_revokes_active_shares_a28(
    client: AsyncClient, worker: Any
) -> None:
    pkg = await _author_with_package(client, worker)
    recipient = await _login(client, f"A28 {uuid.uuid4().hex[:6]}")
    imported = (
        await client.post(
            "/api/v1/imports",
            json={"token": pkg["share"]["token"], "idempotency_key": uuid.uuid4().hex},
            cookies=_cookies(recipient),
            headers=_headers(recipient),
        )
    ).json()

    # author deletes the notebook → active shares revoked
    del_nb = await client.delete(
        f"/api/v1/notebooks/{pkg['nb']['id']}",
        cookies=_cookies(pkg["author"]),
        headers=_headers(pkg["author"]),
    )
    assert del_nb.status_code == 200

    shares = await client.get(
        f"/api/v1/notebooks/{pkg['nb']['id']}/shares",
        cookies=_cookies(pkg["author"]),
    )
    # notebook gone → 404; verify revocation through the import refusal
    assert shares.status_code == 404
    new_import = await client.post(
        "/api/v1/imports",
        json={"token": pkg["share"]["code"], "idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(recipient),
        headers=_headers(recipient),
    )
    assert new_import.status_code in (404, 409)

    # the recipient's copy stays independent and usable (A28)
    results = (
        await client.post(
            f"/api/v1/notebooks/{imported['notebook_id']}/search",
            json={"query": "fotosinteza", "mode": "text"},
            cookies=_cookies(recipient),
        )
    ).json()
    assert len(results) >= 1


async def test_gc_two_phase_keeps_referenced_assets(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    """A18: GC deletes only unreferenced assets; shared ones survive."""
    import sqlalchemy as sa

    from open_notebook.jobs.guguta.gc import gc_sweep

    pkg = await _author_with_package(client, worker)
    recipient = await _login(client, f"GC {uuid.uuid4().hex[:6]}")
    imported = (
        await client.post(
            "/api/v1/imports",
            json={"token": pkg["share"]["token"], "idempotency_key": uuid.uuid4().hex},
            cookies=_cookies(recipient),
            headers=_headers(recipient),
        )
    ).json()

    # an orphan asset with no references at all
    author_me = (
        await client.get("/api/v1/auth/me", cookies=_cookies(pkg["author"]))
    ).json()
    eng = sa.create_engine(guguta_db["migrator_dsn"], isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO source_assets (id, kind, mime_type, byte_size, sha256,"
            " text_content, created_by) VALUES ("
            f"'{uuid.uuid4()}', 'text', 'text/plain', 5, '{uuid.uuid4().hex}',"
            f"'orfan', '{author_me['id']}')"
        )
        # pretend everything is old enough for retention
        conn.exec_driver_sql(
            "UPDATE source_assets SET created_at = now() - interval '400 days'"
        )
    eng.dispose()

    stats = await gc_sweep(
        __import__(
            "open_notebook.database.guguta.engine", fromlist=["x"]
        ).create_engine_for_role(_config(guguta_db["migrator_dsn"]), "api"),
        __import__(
            "open_notebook.storage.guguta.filesystem", fromlist=["x"]
        ).FilesystemStorage("./.guguta-test-storage"),
        retention_days=0,
    )
    assert stats["marked"] >= 1 and stats["deleted"] >= 1

    # the imported copy still works: its asset was referenced and survived
    results = (
        await client.post(
            f"/api/v1/notebooks/{imported['notebook_id']}/search",
            json={"query": "fotosinteza", "mode": "text"},
            cookies=_cookies(recipient),
        )
    ).json()
    assert len(results) >= 1
