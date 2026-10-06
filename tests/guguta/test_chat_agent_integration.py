"""Real PostgreSQL/PDF integration for agent chat, citations and selection."""

import json
import uuid

import pytest
from sqlalchemy import text

from api.services.guguta.chat_agent import NotebookChatAgent
from api.services.guguta.pdf_evidence import PdfPageEvidence
from open_notebook.ai.guguta.chat import ChatAnswer
from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.storage.guguta.filesystem import FilesystemStorage
from tests.guguta.test_chat_agent import turn
from tests.guguta.test_materials_worker import _cookies, _headers
from tests.guguta.test_search_chat import _setup_notebook_with_pdf
from tests.guguta.test_search_chat import client as client_fixture
from tests.guguta.test_search_chat import worker as worker_fixture

client = client_fixture
worker = worker_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_followup_restores_pixels_and_saves_tool_added_citation(
    client, worker, streaming
):
    data = await _setup_notebook_with_pdf(
        client,
        worker,
        "Agent " + uuid.uuid4().hex[:8],
        "Synthetic figure, no count in OCR.",
    )
    nb = data["notebook"]["id"]
    app = client._transport.app
    service = app.state.guguta_chat
    image_service = PdfPageEvidence(
        app.state.guguta_engine, FilesystemStorage("./.guguta-test-storage")
    )
    service._pdf_evidence = image_service
    snapshots = []

    class Provider:
        model_name = "synthetic-vision-tools"

        async def choose_tools(self, messages, tools):
            parts = messages[-1]["content"]
            payload = json.loads(parts[0]["text"])
            assert payload["untrusted_evidence"][0]["locator"]["page"] == 1
            assert any(p["type"] == "image_url" for p in parts)
            if len(payload["untrusted_evidence"]) == 1:
                return turn(
                    "crop_image",
                    {
                        "image_id": "F1",
                        "left": 0.1,
                        "top": 0.1,
                        "right": 0.9,
                        "bottom": 0.9,
                    },
                )
            return turn()

        async def generate(self, question, chunks, history):
            snapshots.append(chunks)
            index = len(chunks) - 1
            return ChatAnswer(
                f"Synthetic grounded answer. [{index + 1}]",
                [index],
                self.model_name,
                10,
                5,
                0.001,
            )

    service._provider = Provider()
    session = (
        await client.post(
            f"/api/v1/notebooks/{nb}/sessions",
            json={},
            cookies=_cookies(data["auth"]),
            headers=_headers(data["auth"]),
        )
    ).json()["id"]
    path = f"/api/v1/notebooks/{nb}/sessions/{session}/messages"
    first = await client.post(
        path,
        json={"content": "pagina PDF 1"},
        cookies=_cookies(data["auth"]),
        headers=_headers(data["auth"]),
    )
    assert first.status_code == 200, first.text
    # Agent activation occurs between turns, as during a real rollout.
    service._agent = NotebookChatAgent(app.state.guguta_search, image_service)
    response = await client.post(
        path + ("/stream" if streaming else ""),
        json={"content": "How many objects are in that picture?"},
        cookies=_cookies(data["auth"]),
        headers=_headers(data["auth"]),
    )
    if streaming:
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert not any(e["event"] == "error" for e in events), events
        result = next(e for e in events if e["event"] == "done")
    else:
        assert response.status_code == 200, response.text
        result = response.json()
    assert len(snapshots[-1]) == 2
    assert snapshots[-1][-1].image_url.startswith("data:image/png;base64,")
    citation = (
        await client.get(
            path + f"/{result['assistant_message_id']}/citations",
            cookies=_cookies(data["auth"]),
        )
    ).json()
    assert len(citation) == 1
    assert citation[0]["locator"]["page"] == 1
    assert citation[0]["locator"]["image_region"] == [0.1, 0.1, 0.9, 0.9]


@pytest.mark.asyncio
async def test_tool_page_access_and_cached_crop_respect_rls_and_selection(
    client, worker
):
    a = await _setup_notebook_with_pdf(
        client,
        worker,
        "Owner " + uuid.uuid4().hex[:8],
        "Synthetic original figure in the authorized owner's manual.",
    )
    b = await _setup_notebook_with_pdf(
        client,
        worker,
        "Other " + uuid.uuid4().hex[:8],
        "Synthetic foreign figure in another person's private manual.",
    )
    app = client._transport.app
    actor = uuid.UUID(
        (await client.get("/api/v1/auth/me", cookies=_cookies(a["auth"]))).json()["id"]
    )
    search = app.state.guguta_search
    own_nb, other_nb = uuid.UUID(a["notebook"]["id"]), uuid.UUID(b["notebook"]["id"])
    own_source = uuid.UUID((await search.list_sources(actor, own_nb))[0]["source_id"])
    assert await search.list_sources(actor, other_nb) == []
    assert await search.open_page(actor, other_nb, own_source, 1) == []
    chunks = await search.open_page(actor, own_nb, own_source, 1)
    pdf = PdfPageEvidence(
        app.state.guguta_engine, FilesystemStorage("./.guguta-test-storage")
    )
    loaded = (await pdf.enrich(actor, own_nb, chunks))[0]
    assert (await pdf.crop(actor, own_nb, loaded, (0.1, 0.1, 0.9, 0.9))).image_url
    await app.state.guguta_sources.update(
        ActorContext(actor_id=actor, display_name="Synthetic"),
        own_nb,
        own_source,
        selected_for_chat=False,
    )
    assert await search.list_sources(actor, own_nb) == []
    assert await search.open_page(actor, own_nb, own_source, 1) == []
    assert await search.authorize_chunks(actor, own_nb, [loaded]) == []
    assert await pdf.crop(actor, own_nb, loaded, (0.1, 0.1, 0.9, 0.9)) is None
    assert (await pdf.enrich(actor, own_nb, [loaded]))[0].image_url is None


@pytest.mark.asyncio
async def test_unindexed_pdf_page_gets_original_pixels_and_nullable_chunk_citation(
    client,
    worker,
    migrator_engine,
):
    data = await _setup_notebook_with_pdf(
        client,
        worker,
        "Pixels " + uuid.uuid4().hex[:8],
        "Synthetic original image evidence without retained OCR chunks.",
    )
    nb = uuid.UUID(data["notebook"]["id"])
    app = client._transport.app
    actor = uuid.UUID(
        (await client.get("/api/v1/auth/me", cookies=_cookies(data["auth"]))).json()[
            "id"
        ]
    )
    search = app.state.guguta_search
    source = uuid.UUID((await search.list_sources(actor, nb))[0]["source_id"])
    with migrator_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM chunks c USING processing_artifacts pa,notebook_sources ns "
                "WHERE c.artifact_id=pa.id AND ns.material_version_id=pa.material_version_id "
                "AND ns.id=:source"
            ),
            {"source": source},
        )
    pdf = PdfPageEvidence(
        app.state.guguta_engine, FilesystemStorage("./.guguta-test-storage")
    )
    unindexed = await search.open_page(actor, nb, source, 1)
    assert unindexed[0].chunk_id is None and unindexed[0].text == ""
    assert (await pdf.enrich(actor, nb, unindexed))[0].image_url

    class Provider:
        model_name = "synthetic-unindexed-vision"

        async def choose_tools(self, messages, tools):
            evidence = json.loads(messages[-1]["content"][0]["text"])[
                "untrusted_evidence"
            ]
            return (
                turn()
                if evidence
                else turn(
                    "open_page",
                    {"source_id": str(source), "page": 1, "page_kind": "pdf"},
                )
            )

        async def generate(self, question, chunks, history):
            assert chunks[0].image_url and chunks[0].chunk_id is None
            return ChatAnswer("Original image evidence. [1]", [0], self.model_name)

    service = app.state.guguta_chat
    service._provider = Provider()
    service._agent = NotebookChatAgent(search, pdf)
    session = (
        await client.post(
            f"/api/v1/notebooks/{nb}/sessions",
            json={},
            cookies=_cookies(data["auth"]),
            headers=_headers(data["auth"]),
        )
    ).json()["id"]
    response = await client.post(
        f"/api/v1/notebooks/{nb}/sessions/{session}/messages",
        json={"content": "pagina PDF 1"},
        cookies=_cookies(data["auth"]),
        headers=_headers(data["auth"]),
    )
    assert response.status_code == 200, response.text
    with migrator_engine.connect() as conn:
        row = conn.execute(
            text("SELECT chunk_id,locator FROM citations WHERE message_id=:message"),
            {"message": uuid.UUID(response.json()["assistant_message_id"])},
        ).first()
    assert row[0] is None and row[1]["page"] == 1
