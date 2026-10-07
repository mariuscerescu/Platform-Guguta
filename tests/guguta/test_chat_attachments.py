"""Real PostgreSQL tests for private attachments, images, quotas and erasure."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine, text

from api.services.guguta.chat_agent import NotebookChatAgent
from api.services.guguta.pdf_evidence import PdfPageEvidence
from open_notebook.ai.guguta.chat import ChatAnswer
from open_notebook.jobs.guguta import queue
from open_notebook.jobs.guguta.handlers import process_material_version
from open_notebook.jobs.guguta.images import normalize_image
from open_notebook.jobs.guguta.parsing import ExtractionError
from tests.guguta.test_materials_worker import _cookies, _drain, _headers, _login
from tests.guguta.test_materials_worker import client as client_fixture
from tests.guguta.test_materials_worker import worker as worker_fixture

client = client_fixture
worker = worker_fixture
pytestmark = pytest.mark.asyncio


def image_bytes(size=(160, 100), fmt="PNG"):
    output = io.BytesIO()
    image = Image.new("RGB", size, "white")
    exif = Image.Exif()
    exif[270] = "Synthetic private metadata"
    image.save(output, format=fmt, exif=exif)
    return output.getvalue()


async def setup(client):
    auth = await _login(client, "Attachments " + uuid.uuid4().hex[:8])
    access = {"cookies": _cookies(auth), "headers": _headers(auth)}
    nb = (
        await client.post("/api/v1/notebooks", json={"title": "Imagini"}, **access)
    ).json()["id"]
    sid = (
        await client.post(f"/api/v1/notebooks/{nb}/sessions", json={}, **access)
    ).json()["id"]
    actor = uuid.UUID((await client.get("/api/v1/auth/me", **access)).json()["id"])
    return SimpleNamespace(
        nb=nb,
        sid=sid,
        actor=actor,
        access=access,
        path=f"/api/v1/notebooks/{nb}/sessions/{sid}/attachments",
    )


async def upload(client, data, files=None):
    response = await client.post(
        data.path,
        files=files
        or [
            ("files", ("exercițiu.png", image_bytes(), "image/png")),
            ("files", ("lecție.txt", b"Fotosinteza glucoza clorofila.", "text/plain")),
        ],
        **data.access,
    )
    assert response.status_code == 201, response.text
    return response.json()["attachments"]


def inspect_db(db, sql, params):
    engine = create_engine(db["migrator_dsn"])
    try:
        with engine.begin() as conn:
            return conn.execute(text(sql), params).mappings().all()
    finally:
        engine.dispose()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
async def test_material_image_ocr_and_original_vision(client, worker, fmt):
    data = await setup(client)
    response = await client.post(
        f"/api/v1/notebooks/{data.nb}/sources/file",
        files={
            "file": (
                f"exercițiu.{fmt.lower()}",
                image_bytes(fmt=fmt),
                f"image/{fmt.lower()}",
            )
        },
        **data.access,
    )
    assert response.status_code == 201, response.text
    source = response.json()["source"]
    assert response.json()["kind"] == "image"

    class OCR:
        async def aclose(self):
            pass

        async def parse_page(self, png, *, page_number):
            assert png.startswith(b"\x89PNG") and page_number == 1
            return SimpleNamespace(markdown="Fotosinteza produce glucoza.")

    worker._image_ocr = OCR()
    await _drain(worker)
    listing = (
        await client.get(f"/api/v1/notebooks/{data.nb}/sources", **data.access)
    ).json()
    assert listing[0]["status"] == "ready" and listing[0]["page_count"] == 1
    search = client._transport.app.state.guguta_search
    chunks = await search.search_notebook(
        data.actor, uuid.UUID(data.nb), "fotosinteza", mode="text"
    )
    assert chunks and chunks[0].locator["image"] is True
    evidence = PdfPageEvidence(search._engine, worker._storage)
    enriched = await evidence.enrich(data.actor, uuid.UUID(data.nb), chunks)
    assert enriched[0].image_url.startswith("data:image/png;base64,")
    crop = await evidence.crop(
        data.actor, uuid.UUID(data.nb), chunks[0], (0.1, 0.1, 0.8, 0.8)
    )
    assert crop and crop.image_url
    downloaded = await client.get(
        f"/api/v1/notebooks/{data.nb}/sources/{source['id']}/download", **data.access
    )
    with Image.open(io.BytesIO(downloaded.content)) as image:
        assert not image.getexif() and image.size == (160, 100)
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert await search.open_page(
        data.actor, uuid.UUID(data.nb), uuid.UUID(source["id"]), 1, page_kind="printed_page"
    )

    class VisionProvider:
        model_name = "synthetic-material-vision"

        def generate(self, question, context_chunks, history):
            assert any(c.image_url for c in context_chunks)
            return ChatAnswer("Imaginea este disponibilă", [0], self.model_name)

    app = client._transport.app
    app.state.guguta_chat._pdf_evidence = evidence
    app.state.guguta_chat._provider = VisionProvider()
    result = await client.post(
        f"/api/v1/notebooks/{data.nb}/sessions/{data.sid}/messages",
        json={"content": "Câte ceasuri sunt în imagine?"},
        **data.access,
    )
    assert result.status_code == 200, result.text


@pytest.mark.parametrize("streaming", [False, True])
async def test_chat_attachments_search_bind_cite_and_delete(
    client, worker, guguta_db, streaming
):
    data = await setup(client)
    app = client._transport.app
    permanent = await client.post(
        f"/api/v1/notebooks/{data.nb}/sources/text",
        json={"title": "Permanent", "text": "Permanent notebook material."},
        **data.access,
    )
    attachments = await upload(client, data)
    blocked = await client.post(
        f"/api/v1/notebooks/{data.nb}/sessions/{data.sid}/messages",
        json={"content": "Ajută-mă", "attachment_ids": [attachments[0]["id"]]},
        **data.access,
    )
    assert blocked.status_code == 422
    await _drain(worker)
    assert (
        len(
            (
                await client.get(f"/api/v1/notebooks/{data.nb}/sources", **data.access)
            ).json()
        )
        == 1
    )
    listed = (await client.get(data.path, **data.access)).json()
    assert len(listed["attachments"]) == 2 and all(
        x["status"] == "ready" for x in listed["attachments"]
    )
    ids = [uuid.UUID(x["id"]) for x in attachments]
    search = app.state.guguta_search.for_session(uuid.UUID(data.sid))
    own_sources = await search.list_sources(data.actor, uuid.UUID(data.nb))
    assert {x["source_id"] for x in own_sources} == {x["id"] for x in attachments} | {
        permanent.json()["source"]["id"]
    }
    for mode in ("text", "vector", "both"):
        result = await search.search_notebook(
            data.actor, uuid.UUID(data.nb), "fotosinteza glucoza", mode=mode
        )
        assert any(c.notebook_source_id == ids[1] for c in result)
    other_sid = (
        await client.post(
            f"/api/v1/notebooks/{data.nb}/sessions", json={}, **data.access
        )
    ).json()["id"]
    other_search = app.state.guguta_search.for_session(uuid.UUID(other_sid))
    assert (
        await other_search.attachment_context(data.actor, uuid.UUID(data.nb), ids) == []
    )
    assert (
        await app.state.guguta_search.attachment_context(
            data.actor, uuid.UUID(data.nb), ids
        )
        == []
    )
    other_sources = await other_search.list_sources(data.actor, uuid.UUID(data.nb))
    assert len(other_sources) == 1
    for mode in ("text", "vector", "both"):
        result = await other_search.search_notebook(
            data.actor, uuid.UUID(data.nb), "fotosinteza glucoza", mode=mode
        )
        assert not any(c.notebook_source_id in ids for c in result)
    chunks = await search.attachment_context(data.actor, uuid.UUID(data.nb), ids)
    image_chunk = next(c for c in chunks if c.notebook_source_id == ids[0])
    evidence = PdfPageEvidence(search._engine, worker._storage).for_session(
        uuid.UUID(data.sid)
    )
    assert (await evidence.enrich(data.actor, uuid.UUID(data.nb), [image_chunk]))[
        0
    ].image_url
    other_evidence = evidence.for_session(uuid.UUID(other_sid))
    assert (await other_evidence.enrich(data.actor, uuid.UUID(data.nb), [image_chunk]))[
        0
    ].image_url is None
    assert (
        await other_evidence.crop(
            data.actor, uuid.UUID(data.nb), image_chunk, (0, 0, 1, 1)
        )
        is None
    )
    assert await other_search.open_page(data.actor, uuid.UUID(data.nb), ids[0], 1) == []
    wrong_path = data.path.replace(data.sid, other_sid)
    for suffix in (f"/{ids[0]}/download", ""):
        response = await client.get(wrong_path + suffix, **data.access)
        assert response.status_code == (404 if suffix else 200)
    foreign = await setup(client)
    assert (await client.get(data.path, **foreign.access)).status_code == 404
    assert (
        await client.post(
            data.path,
            files=[("files", ("x.txt", b"secret", "text/plain"))],
            **foreign.access,
        )
    ).status_code == 404
    invalid = await client.post(
        f"/api/v1/notebooks/{data.nb}/sessions/{other_sid}/messages",
        json={"content": "Ajută-mă", "attachment_ids": [str(ids[0])]},
        **data.access,
    )
    assert invalid.status_code == 404

    class VisionProvider:
        model_name = "synthetic-vision"

        def generate(self, question, context_chunks, history):
            assert any(
                c.image_url and c.notebook_source_id == ids[0] for c in context_chunks
            )
            return ChatAnswer("Imaginea conține exercițiul. [1]", [0], self.model_name)

        async def generate_stream(self, question, context_chunks, history):
            yield self.generate(question, context_chunks, history).content

    app.state.guguta_chat._provider = VisionProvider()
    app.state.guguta_chat._pdf_evidence = evidence
    url = f"/api/v1/notebooks/{data.nb}/sessions/{data.sid}/messages" + (
        "/stream" if streaming else ""
    )
    response = await client.post(
        url,
        json={"content": "Explică imaginea", "attachment_ids": [str(x) for x in ids]},
        headers={
            **data.access["headers"],
            "Idempotency-Key": "attach-" + uuid.uuid4().hex,
        },
        cookies=data.access["cookies"],
    )
    assert response.status_code == 200, response.text
    if streaming:
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert not any(x["event"] == "error" for x in events), events
        assert any(x["event"] == "done" for x in events)
    bound = (await client.get(data.path, **data.access)).json()["attachments"]
    assert all(x["chat_message_id"] for x in bound)
    rows = inspect_db(
        guguta_db,
        "SELECT mv.id AS mv,sa.id AS asset,sa.storage_key FROM material_versions mv "
        "JOIN source_assets sa ON sa.id=mv.source_asset_id WHERE mv.id=ANY(:ids)",
        {"ids": [uuid.UUID(x["material_version_id"]) for x in attachments]},
    )
    assert all(
        worker._storage.exists(x["storage_key"]) for x in rows if x["storage_key"]
    )
    assert (
        await client.delete(data.path.removesuffix("/attachments"), **data.access)
    ).status_code == 200
    assert (await client.get(data.path, **data.access)).status_code == 404
    assert all(
        not worker._storage.exists(x["storage_key"]) for x in rows if x["storage_key"]
    )
    for table, key, values in (
        ("material_versions", "id", [x["mv"] for x in rows]),
        ("source_assets", "id", [x["asset"] for x in rows]),
        ("processing_artifacts", "material_version_id", [x["mv"] for x in rows]),
        ("processing_jobs", "target_id", [x["mv"] for x in rows]),
        ("chat_messages", "session_id", [uuid.UUID(data.sid)]),
    ):
        assert not inspect_db(
            guguta_db, f"SELECT 1 FROM {table} WHERE {key}=ANY(:ids)", {"ids": values}
        )
    assert (
        len(
            (
                await client.get(f"/api/v1/notebooks/{data.nb}/sources", **data.access)
            ).json()
        )
        == 1
    )


async def test_quotas_cumulative_batches_and_concurrent_uploads(client, worker):
    data = await setup(client)
    sources = client._transport.app.state.guguta_sources
    sources._attachment_message_count = 2
    sources._attachment_session_count = 2
    files = [("files", ("x.txt", b"small text", "text/plain"))]
    assert (
        await client.post(data.path, files=files * 3, **data.access)
    ).status_code == 422
    responses = await asyncio.gather(
        *(client.post(data.path, files=files, **data.access) for _ in range(3))
    )
    assert sorted(x.status_code for x in responses) == [201, 201, 422]
    assert len((await client.get(data.path, **data.access)).json()["attachments"]) == 2
    await _drain(worker)
    pending = (await client.get(data.path, **data.access)).json()["attachments"]
    await client.post(
        f"/api/v1/notebooks/{data.nb}/sessions/{data.sid}/messages",
        json={"content": "text", "attachment_ids": [x["id"] for x in pending]},
        **data.access,
    )
    assert (
        await client.post(data.path, files=files, **data.access)
    ).status_code == 422  # conversation cap
    fresh = await setup(client)
    sources._attachment_bytes = 16
    assert (
        await client.post(
            fresh.path,
            files=[("files", ("x.txt", b"a" * 17, "text/plain"))],
            **fresh.access,
        )
    ).status_code == 422
    sources._attachment_bytes = 100
    sources._attachment_total_bytes = 16
    assert (
        await client.post(fresh.path, files=files * 2, **fresh.access)
    ).status_code == 422
    assert (
        await client.post(fresh.path, files=files, **fresh.access)
    ).status_code == 201
    assert (
        await client.post(fresh.path, files=files, **fresh.access)
    ).status_code == 422  # cumulative total


async def test_invalid_image_and_failed_batch_leave_no_sources(client):
    data = await setup(client)
    for content in (
        b"\x89PNG\r\n\x1a\ninvalid",
        image_bytes((8001, 1)),
        image_bytes((5000, 4001)),
    ):
        response = await client.post(
            data.path, files=[("files", ("x.png", content, "image/png"))], **data.access
        )
        assert response.status_code == 422, response.text
    response = await client.post(
        data.path,
        files=[
            ("files", ("x.txt", b"valid text", "text/plain")),
            ("files", ("bad.bin", b"\0\xff", "application/octet-stream")),
        ],
        **data.access,
    )
    assert response.status_code == 422
    assert (await client.get(data.path, **data.access)).json()["attachments"] == []


async def test_deleted_claimed_job_cannot_republish_and_unlink_retries(
    client, worker, guguta_db, monkeypatch
):
    await _drain(worker, 100)
    data = await setup(client)
    attachments = await upload(
        client, data, [("files", ("x.png", image_bytes(), "image/png"))]
    )
    claimed = await queue.claim(worker._engine)
    assert claimed and str(claimed.target_id) == attachments[0]["material_version_id"]
    row = inspect_db(
        guguta_db,
        "SELECT sa.storage_key FROM source_assets sa JOIN material_versions mv "
        "ON mv.source_asset_id=sa.id WHERE mv.id=:mv",
        {"mv": claimed.target_id},
    )[0]
    storage = client._transport.app.state.guguta_sources._storage
    real_delete = storage.delete

    def failed_delete(key):
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(storage, "delete", failed_delete)
    assert (
        await client.delete(data.path.removesuffix("/attachments"), **data.access)
    ).status_code == 200
    assert storage.exists(row["storage_key"])
    assert inspect_db(
        guguta_db,
        "SELECT 1 FROM storage_deletions WHERE storage_key=:key",
        {"key": row["storage_key"]},
    )
    await process_material_version(
        worker._engine, worker._storage, worker._provider, claimed
    )
    assert not inspect_db(
        guguta_db,
        "SELECT 1 FROM processing_artifacts WHERE material_version_id=:mv",
        {"mv": claimed.target_id},
    )
    monkeypatch.setattr(storage, "delete", real_delete)
    assert await worker.process_one()
    assert not storage.exists(row["storage_key"])
    assert not inspect_db(
        guguta_db,
        "SELECT 1 FROM storage_deletions WHERE storage_key=:key",
        {"key": row["storage_key"]},
    )


async def test_animated_images_rejected_and_transparency_preserved():
    output = io.BytesIO()
    image = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    image.save(output, format="PNG")
    with Image.open(io.BytesIO(normalize_image(output.getvalue()))) as normalized:
        assert normalized.getpixel((0, 0))[3] == 0
    output = io.BytesIO()
    image.save(
        output,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGBA", (10, 10), "blue")],
        duration=100,
    )
    with pytest.raises(ExtractionError):
        normalize_image(output.getvalue())


async def test_inflight_ocr_cannot_publish_after_chat_deletion(
    client, worker, guguta_db
):
    await _drain(worker, 100)
    data = await setup(client)
    attachments = await upload(
        client, data, [("files", ("x.png", image_bytes(), "image/png"))]
    )
    started, resume = asyncio.Event(), asyncio.Event()

    class PausedOCR:
        async def parse_page(self, png, *, page_number):
            started.set()
            await resume.wait()
            return SimpleNamespace(markdown="Late OCR result")

        async def aclose(self):
            pass

    worker._image_ocr = PausedOCR()
    task = asyncio.create_task(worker.process_one())
    try:
        await asyncio.wait_for(started.wait(), 5)
        response = await client.delete(
            data.path.removesuffix("/attachments"), **data.access
        )
        assert response.status_code == 200, response.text
    finally:
        resume.set()
        await asyncio.wait_for(task, 5)
    mv = uuid.UUID(attachments[0]["material_version_id"])
    assert not inspect_db(
        guguta_db,
        "SELECT 1 FROM processing_artifacts WHERE material_version_id=:mv",
        {"mv": mv},
    )


async def test_chat_attachments_cannot_be_retained_in_public_catalog(
    client, worker, guguta_db
):
    data = await setup(client)
    attachments = await upload(client, data)
    await _drain(worker)
    inspect_db(
        guguta_db,
        "UPDATE users SET roles=ARRAY['user','catalog_editor'] WHERE id=:actor RETURNING id",
        {"actor": data.actor},
    )
    template = await client.post(
        "/api/v1/admin/catalog/templates",
        json={"slug": "attachment-" + uuid.uuid4().hex, "title": "Temporary sources"},
        **data.access,
    )
    assert template.status_code == 201, template.text
    result = await client.post(
        f"/api/v1/admin/catalog/templates/{template.json()['id']}/versions",
        json={
            "items": [
                {
                    "material_version_id": attachments[0]["material_version_id"],
                    "display_name": "Private attachment",
                }
            ]
        },
        **data.access,
    )
    assert result.status_code == 422, result.text


async def test_followups_keep_attached_text_and_notebook_erasure_with_many_citations(
    client, worker, guguta_db
):
    data = await setup(client)
    app = client._transport.app
    attachments = await upload(client, data)
    await _drain(worker)
    path = f"/api/v1/notebooks/{data.nb}/sessions/{data.sid}/messages"
    result = await client.post(
        path,
        json={
            "content": "Explică materialele",
            "attachment_ids": [x["id"] for x in attachments],
        },
        **data.access,
    )
    assert result.status_code == 200, result.text

    class FollowupProvider:
        model_name = "synthetic-followup"

        def generate(self, question, context_chunks, history):
            assert any("Fotosinteza" in c.text for c in context_chunks)
            return ChatAnswer(
                "Cites both attached sources",
                list(range(len(context_chunks))),
                self.model_name,
            )

    app.state.guguta_chat._provider = FollowupProvider()
    result = await client.post(
        path, json={"content": "Ce scrie în fișierul de text?"}, **data.access
    )
    assert result.status_code == 200, result.text
    result = await client.delete(f"/api/v1/notebooks/{data.nb}", **data.access)
    assert result.status_code == 200, result.text
    assert not inspect_db(
        guguta_db,
        "SELECT 1 FROM notebook_sources WHERE notebook_id=:nb",
        {"nb": uuid.UUID(data.nb)},
    )


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("agent_enabled", [False, True])
async def test_current_docx_takes_priority_over_notebook_image_and_old_citation(
    client, worker, streaming, agent_enabled
):
    data = await setup(client)
    app = client._transport.app

    class OCR:
        async def parse_page(self, png, *, page_number):
            return SimpleNamespace(markdown="Notă medicală scrisă de mână.")

        async def aclose(self):
            pass

    worker._image_ocr = OCR()
    permanent = await client.post(
        f"/api/v1/notebooks/{data.nb}/sources/file",
        files={"file": ("notă.png", image_bytes(), "image/png")}, **data.access,
    )
    assert permanent.status_code == 201
    await _drain(worker)
    evidence = PdfPageEvidence(app.state.guguta_search._engine, worker._storage)
    app.state.guguta_chat._pdf_evidence = evidence
    path = f"/api/v1/notebooks/{data.nb}/sessions/{data.sid}/messages"
    # Save an earlier answer referring to the notebook image.
    prior = await client.post(path, json={"content": "Ce arată imaginea din carnet?"}, **data.access)
    assert prior.status_code == 200, prior.text

    paragraphs = ["Lecție despre fracții.", "Exercițiu: calculează 1/2 + 1/4."] + [
        f"Explicația {i}: adunăm fracțiile cu același numitor." for i in range(3, 10)
    ]
    document = io.BytesIO()
    with zipfile.ZipFile(document, "w") as archive:
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        xml += "".join(f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs)
        archive.writestr("word/document.xml", xml + "</w:body></w:document>")
    attachment = (await upload(client, data, [
        ("files", ("fracții.docx", document.getvalue(),
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    ]))[0]
    await _drain(worker)
    expected_scope = "current_attachment"

    class DocumentProvider:
        model_name = "synthetic-document-tutor"

        async def choose_tools(self, messages, tools):
            content = json.loads(messages[-1]["content"][0]["text"])["untrusted_evidence"]
            assert len(content) == 8 and all(c["source_scope"] == expected_scope for c in content)
            assert all(c["source"] == "fracții.docx" for c in content)
            return {"message": {"role": "assistant", "content": "GATA"}, "usage": (1, 1, 0)}

        def generate(self, question, context_chunks, history):
            assert len(context_chunks) >= 8
            primary = context_chunks[:8]
            assert [c.locator["paragraph"] for c in primary] == list(range(1, 9))
            assert [c.text for c in primary] == paragraphs[:8]
            assert all(c.source_scope == expected_scope and not c.image_url for c in primary)
            # Explicit/search-based supplementary sources remain available and labelled.
            assert all(c.source_scope == (expected_scope if str(c.notebook_source_id) == attachment["id"] else "notebook")
                       for c in context_chunks)
            return ChatAnswer("Documentul DOCX conține fracții. 1/2 + 1/4 = 3/4.", [1], self.model_name)

    app.state.guguta_chat._provider = DocumentProvider()
    if agent_enabled:
        app.state.guguta_chat._agent = NotebookChatAgent(app.state.guguta_search, evidence)
    response = await client.post(path + ("/stream" if streaming else ""), json={
        "content": "Ajută-mă să înțeleg materialul atașat.", "attachment_ids": [attachment["id"]],
    }, **data.access)
    assert response.status_code == 200, response.text
    if streaming:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert not any(event["event"] == "error" for event in events), events
        assert any(event["event"] == "done" for event in events)
    messages = (await client.get(path, **data.access)).json()
    answer = messages[-1]
    assert "DOCX" in answer["content"] and "medicală" not in answer["content"]
    citations = (await client.get(path + f"/{answer['id']}/citations", **data.access)).json()
    assert citations and {c["notebook_source_id"] for c in citations} == {attachment["id"]}
    # A follow-up keeps the document accessible without introducing the old image.
    expected_scope = "chat_attachment"
    followup = await client.post(path, json={"content": "Explică al doilea paragraf."}, **data.access)
    assert followup.status_code == 200, followup.text
