"""L6 tests: catalog lifecycle, instantiation, A02/A03/A05/A14/A15/A18."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
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

async def _promote(client: AsyncClient, guguta_db: dict[str, Any], role: str) -> dict[str, str]:
    auth = await _login(client, f"{role} {uuid.uuid4().hex[:6]}")
    me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
    eng = sa.create_engine(guguta_db["migrator_dsn"])
    with eng.connect() as conn:
        conn.exec_driver_sql(
            f"UPDATE users SET roles = ARRAY['user','{role}'] WHERE id = '{me['id']}'"
        )
        conn.commit()
    eng.dispose()
    return auth


async def _upload_source(client: AsyncClient, auth: dict[str, str], nb_id: str,
                         title: str, text: str) -> str:
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sources/text",
        json={"title": title, "text": text},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["source"]["id"]


async def _setup_editor_with_material(client: AsyncClient, worker: Any,
                                      guguta_db: dict[str, Any]) -> dict[str, Any]:
    editor = await _promote(client, guguta_db, "catalog_editor")
    nb = (await client.post(
        "/api/v1/notebooks", json={"title": "Editor workspace"},
        cookies=_cookies(editor), headers=_headers(editor),
    )).json()
    src1 = await _upload_source(  # noqa: F841 — material ID via list below
        client, editor, nb["id"], "Capitolul unu",
        "Lecția unu prezintă noțiunile de bază ale sistemului solar.",
    )
    src2 = await _upload_source(  # noqa: F841
        client, editor, nb["id"], "Capitolul doi",
        "Lecția doi aprofundează structura planetei Pământ.",
    )
    await _drain(worker)
    sources = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources", cookies=_cookies(editor)
    )).json()
    mv_ids = {s["local_name"]: s["material_version_id"] for s in sources}
    assert len(mv_ids) == 2
    return {"auth": editor, "nb": nb, "mv_ids": mv_ids}


async def test_publish_and_public_catalog_visibility(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    editor = await _setup_editor_with_material(client, worker, guguta_db)

    tpl = (await client.post(
        "/api/v1/admin/catalog/templates",
        json={"slug": f"clasa5-{uuid.uuid4().hex[:6]}", "title": "Clasa a V-a",
              "class_level": "V", "discipline": "Științe", "edition": "2026"},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    assert tpl["status"] == "draft"

    version = (await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions",
        json={"items": [
            {"material_version_id": editor["mv_ids"]["Capitolul unu"],
             "display_name": "Capitolul unu"},
            {"material_version_id": editor["mv_ids"]["Capitolul doi"],
             "display_name": "Capitolul doi"},
        ]},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    assert version["version"] == 1

    # drafts invisible in the public catalog
    student = await _login(client, f"Elev {uuid.uuid4().hex[:6]}")
    listing = (await client.get(
        "/api/v1/catalog/templates", cookies=_cookies(student)
    )).json()
    assert all(t["id"] != tpl["id"] for t in listing)

    published = await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{version['id']}/publish",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )
    assert published.status_code == 200, published.text

    listing = (await client.get(
        "/api/v1/catalog/templates", cookies=_cookies(student)
    )).json()
    mine = [t for t in listing if t["id"] == tpl["id"]]
    assert len(mine) == 1
    assert mine[0]["material_count"] == 2
    assert mine[0]["current_version"] == 1


async def test_instantiate_two_independent_copies_and_a03(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    editor = await _setup_editor_with_material(client, worker, guguta_db)
    tpl = (await client.post(
        "/api/v1/admin/catalog/templates",
        json={"slug": f"inst-{uuid.uuid4().hex[:6]}", "title": "Șablon instanțiere",
              "class_level": "V", "discipline": "Biologie"},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    version = (await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions",
        json={"items": [
            {"material_version_id": editor["mv_ids"]["Capitolul unu"],
             "display_name": "Capitolul unu"},
        ]},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    assert (await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{version['id']}/publish",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).status_code == 200

    a = await _login(client, f"Copy A {uuid.uuid4().hex[:6]}")
    b = await _login(client, f"Copy B {uuid.uuid4().hex[:6]}")

    inst_a = (await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(a), headers=_headers(a),
    )).json()
    inst_b = (await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(b), headers=_headers(b),
    )).json()

    # A02: different local IDs, same pinned version, zero personal activity
    assert inst_a["notebook_id"] != inst_b["notebook_id"]
    assert inst_a["template_version_id"] == inst_b["template_version_id"]
    assert inst_a["material_count"] == 1

    notes_a = (await client.get(
        f"/api/v1/notebooks/{inst_a['notebook_id']}/notes", cookies=_cookies(a)
    )).json()
    sessions_a = (await client.get(
        f"/api/v1/notebooks/{inst_a['notebook_id']}/sessions", cookies=_cookies(a)
    )).json()
    assert notes_a == [] and sessions_a == []

    # A03: A removes the material from their copy; B's copy and the template
    # remain valid; B can still search the shared material.
    src_a = (await client.get(
        f"/api/v1/notebooks/{inst_a['notebook_id']}/sources", cookies=_cookies(a)
    )).json()
    del_resp = await client.delete(
        f"/api/v1/notebooks/{inst_a['notebook_id']}/sources/{src_a[0]['id']}",
        cookies=_cookies(a), headers=_headers(a),
    )
    assert del_resp.status_code == 200

    results_b = (await client.post(
        f"/api/v1/notebooks/{inst_b['notebook_id']}/search",
        json={"query": "sistemul solar", "mode": "text"},
        cookies=_cookies(b),
    )).json()
    assert len(results_b) >= 1

    # the template remains instantiable
    again = await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(b), headers=_headers(b),
    )
    assert again.status_code == 201

    # A18: deleting a copy leaves the material usable by the other copy
    del_nb = await client.delete(
        f"/api/v1/notebooks/{inst_a['notebook_id']}",
        cookies=_cookies(a), headers=_headers(a),
    )
    assert del_nb.status_code == 200
    results_b2 = (await client.post(
        f"/api/v1/notebooks/{inst_b['notebook_id']}/search",
        json={"query": "sistemul solar", "mode": "text"},
        cookies=_cookies(b),
    )).json()
    assert len(results_b2) >= 1


async def test_idempotent_instantiation_a15(client: AsyncClient, worker: Any,
                                            guguta_db: dict[str, Any]) -> None:
    editor = await _setup_editor_with_material(client, worker, guguta_db)
    tpl = (await client.post(
        "/api/v1/admin/catalog/templates",
        json={"slug": f"idem-{uuid.uuid4().hex[:6]}", "title": "Șablon idem"},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    version = (await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions",
        json={"items": [{"material_version_id": editor["mv_ids"]["Capitolul unu"],
                         "display_name": "Capitolul unu"}]},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{version['id']}/publish",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )
    user = await _login(client, f"Idem user {uuid.uuid4().hex[:6]}")

    r1 = await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": "same-key"},
        cookies=_cookies(user), headers=_headers(user),
    )
    r2 = await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": "same-key"},
        cookies=_cookies(user), headers=_headers(user),
    )
    assert r1.status_code == 201 and r2.status_code in (200, 201)
    assert r1.json()["notebook_id"] == r2.json()["notebook_id"]
    assert r2.json().get("replayed") is True

    # intentional new instantiation with a new key creates a new copy
    r3 = await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": "other-key"},
        cookies=_cookies(user), headers=_headers(user),
    )
    assert r3.status_code == 201
    assert r3.json()["notebook_id"] != r1.json()["notebook_id"]


async def test_start_again_uses_current_published_edition_a05_a14(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    editor = await _setup_editor_with_material(client, worker, guguta_db)
    tpl = (await client.post(
        "/api/v1/admin/catalog/templates",
        json={"slug": f"edit-{uuid.uuid4().hex[:6]}", "title": "Șablon ediții"},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    v1 = (await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions",
        json={"items": [{"material_version_id": editor["mv_ids"]["Capitolul unu"],
                         "display_name": "Capitolul unu"}]},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{v1['id']}/publish",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )
    user = await _login(client, f"Ed user {uuid.uuid4().hex[:6]}")
    first = (await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(user), headers=_headers(user),
    )).json()
    assert first["version"] == 1

    # editor publishes edition 2 with BOTH materials
    v2 = (await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions",
        json={"items": [
            {"material_version_id": editor["mv_ids"]["Capitolul unu"],
             "display_name": "Capitolul unu"},
            {"material_version_id": editor["mv_ids"]["Capitolul doi"],
             "display_name": "Capitolul doi"},
        ]},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{v2['id']}/publish",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )

    # A14: the existing copy is NOT updated (still edition 1, one material)
    src_first = (await client.get(
        f"/api/v1/notebooks/{first['notebook_id']}/sources", cookies=_cookies(user)
    )).json()
    assert len(src_first) == 1

    # A05: „Începe din nou" → new copy from the current published edition
    again = (await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(user), headers=_headers(user),
    )).json()
    assert again["version"] == 2 and again["material_count"] == 2

    # manifest immutability: publishing v2 again is blocked (not draft)
    republish = await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{v1['id']}/publish",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )
    assert republish.status_code == 422


async def test_retire_blocks_new_instantiations(client: AsyncClient, worker: Any,
                                                guguta_db: dict[str, Any]) -> None:
    editor = await _setup_editor_with_material(client, worker, guguta_db)
    tpl = (await client.post(
        "/api/v1/admin/catalog/templates",
        json={"slug": f"ret-{uuid.uuid4().hex[:6]}", "title": "Șablon retras"},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    version = (await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions",
        json={"items": [{"material_version_id": editor["mv_ids"]["Capitolul unu"],
                         "display_name": "Capitolul unu"}]},
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )).json()
    await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{version['id']}/publish",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )
    user = await _login(client, f"Ret user {uuid.uuid4().hex[:6]}")
    copy = (await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(user), headers=_headers(user),
    )).json()

    retire = await client.post(
        f"/api/v1/admin/catalog/templates/{tpl['id']}/versions/{version['id']}/retire",
        cookies=_cookies(editor["auth"]), headers=_headers(editor["auth"]),
    )
    assert retire.status_code == 200

    # new instantiations blocked with a clear, non-500 error
    blocked = await client.post(
        f"/api/v1/catalog/templates/{tpl['id']}/instances",
        json={"idempotency_key": uuid.uuid4().hex},
        cookies=_cookies(user), headers=_headers(user),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "retired"

    # the existing copy keeps working (search still returns the material)
    results = (await client.post(
        f"/api/v1/notebooks/{copy['notebook_id']}/search",
        json={"query": "sistemul solar", "mode": "text"},
        cookies=_cookies(user),
    )).json()
    assert len(results) >= 1
