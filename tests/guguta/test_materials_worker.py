"""L3 tests: materials upload, worker pipeline, leases, isolation.

A minimal but valid single-page PDF is generated programmatically (correct
xref offsets) so the pipeline tests run without external fixtures.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from open_notebook.database.guguta.config import GugutaConfig

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------


def _make_pdf(page_texts: list[str]) -> bytes:
    """Build a valid PDF with the given per-page text (real xref)."""
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    add(b"<< /Type /Pages /Kids %s /Count %d >>" % (
        b"[" + b" ".join(f"{3 + i * 2} 0 R".encode() for i in range(len(page_texts))) + b"]",
        len(page_texts),
    ))  # 2
    font_num = 3 + len(page_texts) * 2
    for i, text in enumerate(page_texts):
        page_num = add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {4 + i * 2} 0 R /Resources << /Font << /F1 {font_num} 0 R >> >> >>".encode()
        )
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
        add(
            b"<< /Length " + str(len(stream)).encode() + b" >> stream\n" + stream + b"\nendstream"
        )
        assert page_num == 3 + i * 2
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF".encode()
    )
    return out.getvalue()


def _config(api_dsn: str) -> GugutaConfig:
    return GugutaConfig(
        environment="ci",
        auth_mode="test",
        database_url_api=api_dsn,
        database_url_worker=api_dsn,
        database_url_migrator=api_dsn,
        server_secret="test-secret-not-for-production",
        cors_origins=["http://localhost:3000"],
        public_origin="http://localhost:3000",
        storage_root="./.guguta-test-storage",
    )


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
        def __init__(self) -> None:  # skip Worker.__init__ (config-driven)
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
    assert resp.status_code == 200, resp.text
    return {
        "csrf": resp.headers.get("X-Guguta-CSRF", ""),
        "cookie": resp.cookies.get("guguta_session", ""),
    }


# ---------------------------------------------------------------------------
# Storage adapter
# ---------------------------------------------------------------------------


async def test_storage_rejects_traversal(tmp_path: Any) -> None:
    from open_notebook.storage.guguta.base import StorageKeyRejected
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    store = FilesystemStorage(str(tmp_path))
    for bad in ("../evil", "a/../b", "C:/x", "a\\b", "/abs", "a/b/../c"):
        with pytest.raises(StorageKeyRejected):
            store.read_bytes(bad)
    key = store.save_bytes(b"payload")
    assert store.exists(key)
    assert store.read_bytes(key) == b"payload"
    assert store.delete(key)
    assert not store.exists(key)


# ---------------------------------------------------------------------------
# Upload + worker pipeline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("failure_stage", ["ocr", "publication"])
async def test_exhausted_transient_failure_is_visible_and_retry_recovers(
    client: AsyncClient, worker: Any, monkeypatch: Any, failure_stage: str,
) -> None:
    """A failed dependency must not leave the material processing forever."""
    from sqlalchemy import text

    from open_notebook.jobs.guguta import handlers
    from open_notebook.jobs.guguta.pdf_pipeline import PdfPipelineUnavailable

    await _drain(worker)
    auth = await _login(client, f"Retry {uuid.uuid4().hex[:6]}")
    nb = (await client.post(
        "/api/v1/notebooks", json={"title": "Retry material"},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    uploaded = (await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/file",
        files={"file": ("manual.pdf", _make_pdf(["A readable manual page."]), "application/pdf")},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    job_id = uuid.UUID(uploaded["job_id"])
    source_path = f"/api/v1/notebooks/{nb['id']}/sources/{uploaded['source']['id']}"
    async with worker._engine.begin() as conn:
        await conn.execute(
            text("UPDATE processing_jobs SET max_attempts = 2 WHERE id = :id"),
            {"id": job_id},
        )

    class OfflineOcr:
        async def extract(self, data: bytes) -> Any:
            raise PdfPipelineUnavailable("OCR temporarily unavailable")

    async def unavailable_publication(*args: Any) -> Any:
        raise RuntimeError("publication temporarily unavailable")

    with monkeypatch.context() as patch:
        if failure_stage == "ocr":
            patch.setattr(worker, "_pdf_extractor", OfflineOcr(), raising=False)
        else:
            patch.setattr(handlers, "_ensure_embedding_space", unavailable_publication)
        assert await worker.process_one()
        source = (await client.get(source_path, cookies=_cookies(auth))).json()
        job = (await client.get(f"/api/v1/jobs/{job_id}", cookies=_cookies(auth))).json()
        assert source["status"] == "processing"
        assert job["status"] == "queued"
        assert job["completed_at"] is None

        async with worker._engine.begin() as conn:
            await conn.execute(
                text("UPDATE processing_jobs SET run_after = now() WHERE id = :id"),
                {"id": job_id},
            )
        assert await worker.process_one()
        source = (await client.get(source_path, cookies=_cookies(auth))).json()
        job = (await client.get(f"/api/v1/jobs/{job_id}", cookies=_cookies(auth))).json()
        assert job["status"] == "failed" and job["attempts"] == 2
        assert job["completed_at"] is not None
        assert source["status"] == "error"
        assert source["status_detail"] == job["last_error"]
        assert "temporarily unavailable" in source["status_detail"]

    retried = await client.post(
        f"{source_path}/retry", cookies=_cookies(auth), headers=_headers(auth),
    )
    assert retried.status_code == 200 and retried.json()["requeued"] is True
    job = (await client.get(f"/api/v1/jobs/{job_id}", cookies=_cookies(auth))).json()
    assert job["status"] == "queued" and job["attempts"] == 0
    assert job["completed_at"] is None
    assert await worker.process_one()
    source = (await client.get(source_path, cookies=_cookies(auth))).json()
    assert source["status"] == "ready" and source["status_detail"] is None


@pytest.mark.parametrize("expiry", ["lease", "attempts", "deadline"])
async def test_queue_expiry_marks_material_error(
    client: AsyncClient, worker: Any, expiry: str,
) -> None:
    """Worker death and deadlines also stop the source's processing spinner."""
    from sqlalchemy import text

    await _drain(worker)
    auth = await _login(client, f"Expired {uuid.uuid4().hex[:6]}")
    nb = (await client.post(
        "/api/v1/notebooks", json={"title": "Expired material"},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    uploaded = (await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={"text": "Text for an expired processing job.", "title": "Expired"},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    updates = {
        "lease": "status = 'running', attempts = max_attempts, lease_token = 'expired', "
                 "lease_until = now() - interval '1 hour'",
        "attempts": "attempts = max_attempts",
        "deadline": "deadline = now() - interval '1 hour'",
    }
    async with worker._engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE processing_jobs SET {updates[expiry]} WHERE id = :id"),
            {"id": uuid.UUID(uploaded["job_id"])},
        )
    await worker.process_one()
    source = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{uploaded['source']['id']}",
        cookies=_cookies(auth),
    )).json()
    job = (await client.get(
        f"/api/v1/jobs/{uploaded['job_id']}", cookies=_cookies(auth),
    )).json()
    assert job["status"] == "failed" and job["completed_at"] is not None
    assert source["status"] == "error" and source["status_detail"] == job["last_error"]


async def test_material_failure_rolls_back_job_and_source_together(
    client: AsyncClient, worker: Any, monkeypatch: Any,
) -> None:
    from open_notebook.jobs.guguta import queue

    await _drain(worker)
    auth = await _login(client, f"Atomic {uuid.uuid4().hex[:6]}")
    nb = (await client.post(
        "/api/v1/notebooks", json={"title": "Atomic material"},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    uploaded = (await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={"text": "Text for atomic failure handling.", "title": "Atomic"},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    claimed = await queue.claim(worker._engine)
    assert claimed is not None and str(claimed.id) == uploaded["job_id"]
    original = queue._mark_failed_material_sources

    async def interrupted_transaction(conn: Any, jobs: Any) -> None:
        await original(conn, jobs)
        raise RuntimeError("connection interrupted before commit")

    with monkeypatch.context() as patch:
        patch.setattr(queue, "_mark_failed_material_sources", interrupted_transaction)
        with pytest.raises(RuntimeError, match="before commit"):
            await queue.fail(
                worker._engine, claimed.id, claimed.lease_token, "terminal error",
                target_revision=claimed.target_revision, permanent=True,
            )
    source = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{uploaded['source']['id']}",
        cookies=_cookies(auth),
    )).json()
    job = (await client.get(
        f"/api/v1/jobs/{claimed.id}", cookies=_cookies(auth),
    )).json()
    assert source["status"] == "processing" and source["status_detail"] is None
    assert job["status"] == "running" and job["last_error"] is None
    await queue.fail(
        worker._engine, claimed.id, claimed.lease_token, "terminal error",
        target_revision=claimed.target_revision, permanent=True,
    )
    retried = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/{uploaded['source']['id']}/retry",
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert retried.status_code == 200 and retried.json()["requeued"] is True
    with pytest.raises(queue.LeaseStale):
        await queue.fail(
            worker._engine, claimed.id, claimed.lease_token, "stale failure",
            target_revision=claimed.target_revision, permanent=True,
        )
    source = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{uploaded['source']['id']}",
        cookies=_cookies(auth),
    )).json()
    assert source["status"] == "processing" and source["status_detail"] is None
    assert await worker.process_one()


async def test_upload_pdf_full_pipeline(client: AsyncClient, worker: Any) -> None:
    auth = await _login(client, f"Elev PDF {uuid.uuid4().hex[:6]}")
    nb = (
        await client.post(
            "/api/v1/notebooks", json={"title": "Carnet PDF"},
            cookies=_cookies(auth), headers=_headers(auth),
        )
    ).json()
    pdf = _make_pdf(["Text pagina unu despre fotosinteză.",
                     "Pagina doi continuă despre fotosinteză."])
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/file",
        files={"file": ("manual.pdf", pdf, "application/pdf")},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "pdf"
    source_id = body["source"]["id"]
    job_id = body["job_id"]

    ran = await _drain(worker)
    assert ran >= 1

    detail = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}",
        cookies=_cookies(auth),
    )).json()
    assert detail["status"] == "ready"
    assert detail["page_count"] == 2

    job = (await client.get(f"/api/v1/jobs/{job_id}", cookies=_cookies(auth))).json()
    assert job["status"] == "succeeded"

    # download returns the original bytes (authorized proxy)
    dl = await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}/download",
        cookies=_cookies(auth),
    )
    assert dl.status_code == 200
    assert dl.content.startswith(b"%PDF-")


async def test_text_source_pipeline_and_selection_revision(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    auth = await _login(client, f"Elev Text {uuid.uuid4().hex[:6]}")
    nb = (
        await client.post(
            "/api/v1/notebooks", json={"title": "Carnet text"},
            cookies=_cookies(auth), headers=_headers(auth),
        )
    ).json()
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={"title": " notițe lecție ", "text": "Primul paragraf.\n\nAl doilea paragraf."},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201
    body = resp.json()
    source_id = body["source"]["id"]
    assert body["source"]["local_name"] == "notițe lecție"  # trimmed

    await _drain(worker)
    detail = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}", cookies=_cookies(auth)
    )).json()
    assert detail["status"] == "ready"

    # selection change bumps context_revision (A17)
    before = (await client.get(f"/api/v1/notebooks/{nb['id']}", cookies=_cookies(auth))).json()
    await client.patch(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}",
        json={"selected_for_chat": False},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    after = (await client.get(f"/api/v1/notebooks/{nb['id']}", cookies=_cookies(auth))).json()
    assert after["context_revision"] == before["context_revision"] + 1

    # deletion bumps revision too, and the source disappears
    await client.delete(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}",
        cookies=_cookies(auth), headers=_headers(auth),
    )
    after2 = (await client.get(f"/api/v1/notebooks/{nb['id']}", cookies=_cookies(auth))).json()
    assert after2["context_revision"] == after["context_revision"] + 1
    resp = await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}", cookies=_cookies(auth)
    )
    assert resp.status_code == 404


async def test_scanned_pdf_fails_explicitly_not_ready(
    client: AsyncClient, worker: Any
) -> None:
    """A24: a PDF without usable text is explained, never 'ready'."""
    auth = await _login(client, f"Elev Scan {uuid.uuid4().hex[:6]}")
    nb = (
        await client.post(
            "/api/v1/notebooks", json={"title": "Carnet scan"},
            cookies=_cookies(auth), headers=_headers(auth),
        )
    ).json()
    # two pages whose content streams contain no text operators
    scanned = _make_pdf(["", ""])  # helper writes Tj only when text; empty â†’ BT/ET only
    # ensure no text: replace text ops
    scanned = scanned.replace(b"Tj", b" ")
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/file",
        files={"file": ("scanat.pdf", scanned, "application/pdf")},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201
    source_id = resp.json()["source"]["id"]
    await _drain(worker)
    detail = (await client.get(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}", cookies=_cookies(auth)
    )).json()
    assert detail["status"] == "error"
    assert "scanat" in (detail["status_detail"] or "").lower()

    # manual retry is possible for errored sources
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}/retry",
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 200 and resp.json()["requeued"] is True


async def test_invalid_file_rejected(client: AsyncClient) -> None:
    auth = await _login(client, f"Elev Bin {uuid.uuid4().hex[:6]}")
    nb = (
        await client.post(
            "/api/v1/notebooks", json={"title": "Carnet bin"},
            cookies=_cookies(auth), headers=_headers(auth),
        )
    ).json()
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/file",
        files={"file": ("binar.bin", b"\x00\x01\x02\xff\xfe" * 100, "application/octet-stream")},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 422
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/file",
        files={"file": ("vid.pdf", b"", "application/pdf")},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 422


async def test_sources_isolated_between_users(client: AsyncClient, worker: Any) -> None:
    """A04 groundwork at API level: B cannot see or download A's material."""
    auth_a = await _login(client, f"Elev A {uuid.uuid4().hex[:6]}")
    auth_b = await _login(client, f"Elev B {uuid.uuid4().hex[:6]}")
    nb = (
        await client.post(
            "/api/v1/notebooks", json={"title": "Carnet A privat"},
            cookies=_cookies(auth_a), headers=_headers(auth_a),
        )
    ).json()
    resp = await client.post(
        f"/api/v1/notebooks/{nb['id']}/sources/text",
        json={"text": "Conținut privat al lui A.", "title": "privat"},
        cookies=_cookies(auth_a), headers=_headers(auth_a),
    )
    source_id = resp.json()["source"]["id"]
    job_id = resp.json()["job_id"]

    for path in (
        f"/api/v1/notebooks/{nb['id']}/sources",
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}",
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}/download",
        f"/api/v1/jobs/{job_id}",
        f"/api/v1/notebooks/{nb['id']}/sources/{source_id}/retry",
    ):
        resp = await client.request(
            "GET" if "retry" not in path else "POST", path,
            cookies=_cookies(auth_b), headers=_headers(auth_b),
        )
        assert resp.status_code in (404, 405), f"{path}: {resp.status_code}"


async def test_stale_lease_cannot_complete(worker: Any, guguta_db: dict[str, Any]) -> None:
    """An expired lease lets another worker claim; the old token is refused."""
    from sqlalchemy import text as st

    from open_notebook.database.guguta.engine import create_engine_for_role
    from open_notebook.jobs.guguta.queue import (
        LeaseStale,
        claim,
        complete,
        enqueue,
        heartbeat,
    )

    engine = create_engine_for_role(_config(guguta_db["api_dsn"]), "api")
    worker_engine = create_engine_for_role(_config(guguta_db["worker_dsn"]), "worker")
    try:
        # drain leftovers from earlier tests so claim() returns OUR job
        while await worker.process_one():
            pass
        async with engine.begin() as conn:
            user_id = (
                await conn.execute(
                    st("SELECT guguta_provision_user('test', :s, :s)"),
                    {"s": f"lease-{uuid.uuid4().hex[:8]}"},
                )
            ).scalar_one()
            await conn.execute(
                st("SELECT set_config('app.actor_id', :a, true)"),
                {"a": str(user_id)},
            )
            asset_id = (
                await conn.execute(
                    st(
                        "INSERT INTO source_assets (id, kind, mime_type, byte_size, sha256,"
                        " text_content, created_by) VALUES (:i, 'text', 'text/plain', 10,"
                        " :sha, 'continut', :by) RETURNING id"
                    ),
                    {"i": uuid.uuid4(), "sha": uuid.uuid4().hex, "by": user_id},
                )
            ).scalar_one()
            mv_id = (
                await conn.execute(
                    st(
                        "INSERT INTO material_versions (id, source_asset_id, title, created_by)"
                        " VALUES (:i, :a, 'v', :by) RETURNING id"
                    ),
                    {"i": uuid.uuid4(), "a": asset_id, "by": user_id},
                )
            ).scalar_one()
            job_id = await enqueue(
                engine, conn,
                job_type="process_material_version",
                target_type="material_version",
                target_id=mv_id,
                actor_id=user_id,
            )

        first = await claim(worker_engine)
        assert first is not None and first.id == job_id

        # heartbeat extends the lease
        assert await heartbeat(worker_engine, first.id, first.lease_token)

        # expire the lease -> second worker claims the same job
        import sqlalchemy as sa

        sync = sa.create_engine(guguta_db["migrator_dsn"])
        with sync.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE processing_jobs SET lease_until = now() - interval '1 hour'"
                f" WHERE id = '{first.id}'"
            )
            conn.commit()
        second = await claim(worker_engine)
        assert second is not None and second.id == first.id
        assert second.lease_token != first.lease_token

        # the stale worker cannot complete
        with pytest.raises(LeaseStale):
            await complete(worker_engine, first.id, first.lease_token, target_revision=1)
        # the new owner can
        await complete(worker_engine, second.id, second.lease_token, target_revision=1)
    finally:
        await engine.dispose()
        await worker_engine.dispose()
