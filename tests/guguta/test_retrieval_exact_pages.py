"""General regressions: locators, RLS, PDF evidence and concurrent SSE.

Fixtures use a disposable test PostgreSQL database, never production data.
The synthetic exercise and page numbers are independent of the live benchmark.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from api.services.guguta.search import (
    RetrievedChunk,
    _diverse_pages,
    _interleave_ids,
    _or_tsquery,
    requested_page,
)
from tests.guguta.test_materials_worker import _cookies, _headers
from tests.guguta.test_search_chat import _setup_notebook_with_pdf
from tests.guguta.test_search_chat import client as client_fixture
from tests.guguta.test_search_chat import worker as worker_fixture

client = client_fixture
worker = worker_fixture


def test_vector_candidates_cannot_be_starved_by_text_hits():
    ids = {value: uuid.UUID(int=value) for value in (1, 2, 3, 4, 8, 9, 10)}
    assert _interleave_ids(
        [ids[value] for value in (1, 2, 3, 4)],
        [ids[value] for value in (8, 9, 2, 10)],
    )[:4] == [ids[value] for value in (1, 8, 2, 9)]


def test_romanian_query_fold_and_retrieval_instructions():
    assert _or_tsquery("Citează manualul: fracțiile şi operaţiile") == "fractiile | operatiile"
    assert _or_tsquery("ȘTIINȚĂ ştiinţă") == "stiinta"
    assert _or_tsquery("!!!") == ""


@pytest.mark.asyncio
async def test_text_search_understands_inflection_and_old_diacritics(client, worker, migrator_engine):
    a = await _setup_notebook_with_pdf(client,worker,"Grammar "+uuid.uuid4().hex[:8],
                                     "Synthetic lexical evidence.")
    # The tiny test PDF generator uses Helvetica without a Unicode character
    # map. Supply proper Unicode directly to the synthetic indexed chunk;
    # this regression tests retrieval, not that PDF fixture's font encoding.
    with migrator_engine.begin() as conn:
        conn.execute(text(
            "UPDATE chunks c SET text=:value FROM processing_artifacts pa "
            "JOIN notebook_sources ns ON ns.material_version_id=pa.material_version_id "
            "WHERE c.artifact_id=pa.id AND ns.notebook_id=:nb"
        ), {"value":"Cercetătorii studiază fracţii şi operaţii matematice.",
            "nb":uuid.UUID(a["notebook"]["id"])})
    response = await client.post(
        f"/api/v1/notebooks/{a['notebook']['id']}/search",
        json={"query":"Citează manualul despre cercetătorul care studiază fracțiile.","mode":"text"},
        cookies=_cookies(a["auth"]),
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert "frac" in response.json()[0]["text"]


def test_duplicate_page_chunks_do_not_crowd_out_other_topics():
    material_version_id = uuid.uuid4()
    source_id = uuid.uuid4()
    chunks = [
        RetrievedChunk(
            chunk_id=uuid.UUID(int=i),
            text="Synthetic page text",
            locator={"page": page},
            notebook_source_id=source_id,
            material_version_id=material_version_id,
            local_name="book",
            score=1.0,
        )
        for i, page in enumerate([7, 7, 7, 8, 9])
    ]
    assert [c.locator["page"] for c in _diverse_pages(chunks,3)] == [7,8,9]
    assert len(_diverse_pages(chunks,8)) == 5


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Exercițiul 31 de la pagina tipărită 74", ("printed_page", 74)),
        ("pagina PDF 101, exercițiul 2", ("page", 101)),
        ("pag. 9", ("printed_page", 9)),
        ("pagina 18", ("printed_page", 18)),
        ("Numerotarea paginilor cu 183 de cifre", None),
        ("Exercițiul 17", None),
    ],
)
def test_explicit_page_convention(query, expected):
    assert requested_page(query) == expected


@pytest.mark.asyncio
async def test_exact_page_is_not_reranked_and_is_isolated(
    client, worker, migrator_engine
):
    a = await _setup_notebook_with_pdf(
        client,
        worker,
        "Page " + uuid.uuid4().hex[:8],
        "Synthetic page exercise evidence.",
    )
    b = await _setup_notebook_with_pdf(
        client,
        worker,
        "Foreign " + uuid.uuid4().hex[:8],
        "Foreign private page evidence.",
    )
    nb = a["notebook"]["id"]
    with migrator_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE chunks SET locator=jsonb_build_object('page',19,'printed_page',7)"
            )
        )
    service = client._transport.app.state.guguta_search

    async def forbidden(*args):
        raise AssertionError("exact page retrieval called an AI provider")

    service._provider = SimpleNamespace(embed=forbidden, model_name="not-used")
    service._reranker = SimpleNamespace(rank=forbidden)
    for query in ("pagina PDF 19, exercițiul 5", "pagina tipărită 7, exercițiul 5"):
        response = await client.post(
            f"/api/v1/notebooks/{nb}/search",
            json={"query": query},
            cookies=_cookies(a["auth"]),
        )
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1
        assert "Foreign" not in response.json()[0]["text"]
        assert response.json()[0]["mode"] == "locator"
    absent = await client.post(
        f"/api/v1/notebooks/{nb}/search",
        json={"query": "pagina PDF 7"},
        cookies=_cookies(a["auth"]),
    )
    assert absent.json() == []  # Never assume PDF = printed+1.
    foreign = await client.post(
        f"/api/v1/notebooks/{b['notebook']['id']}/search",
        json={"query": "pagina PDF 19"},
        cookies=_cookies(a["auth"]),
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_pdf_cache_still_checks_selected_source(client, worker):
    from api.services.guguta.pdf_evidence import PdfPageEvidence
    from open_notebook.auth.guguta.actor import ActorContext
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    a = await _setup_notebook_with_pdf(
        client,
        worker,
        "Images " + uuid.uuid4().hex[:8],
        "Image evidence for original PDF page.",
    )
    nb = uuid.UUID(a["notebook"]["id"])
    app = client._transport.app
    me = await client.get("/api/v1/auth/me", cookies=_cookies(a["auth"]))
    actor = uuid.UUID(me.json()["id"])
    search = app.state.guguta_search
    chunks = await search.search_notebook(actor, nb, "pagina PDF 1")
    enricher = PdfPageEvidence(
        app.state.guguta_engine, FilesystemStorage("./.guguta-test-storage")
    )
    enriched = await enricher.enrich(actor, nb, chunks)
    assert enriched[0].image_url is not None
    assert enriched[0].image_url.startswith("data:image/png;base64,")
    assert enriched[0].chunk_id == chunks[0].chunk_id
    assert enriched[0].extracted_text == chunks[0].text
    await app.state.guguta_sources.update(
        ActorContext(actor_id=actor, display_name="Synthetic"),
        nb,
        chunks[0].notebook_source_id,
        selected_for_chat=False,
    )
    deselected = await enricher.enrich(actor, nb, chunks)
    assert all(c.image_url is None for c in deselected)


@pytest.mark.asyncio
async def test_sse_citations_are_request_local(client, worker):
    from open_notebook.ai.guguta.chat import ChatAnswer

    a = await _setup_notebook_with_pdf(
        client, worker, "Streams " + uuid.uuid4().hex[:8], "Synthetic stream evidence."
    )
    nb = a["notebook"]["id"]
    app = client._transport.app
    me = await client.get("/api/v1/auth/me", cookies=_cookies(a["auth"]))
    actor = uuid.UUID(me.json()["id"])
    actual = await app.state.guguta_search.search_notebook(
        actor, uuid.UUID(nb), "pagina PDF 1"
    )
    context = [actual[0], actual[0]]

    async def retrieve(*args):
        return context

    app.state.guguta_chat._retrieve = retrieve

    class Provider:
        model_name = "synthetic-request-local"
        last_cited = [99]  # A shared legacy value must NEVER affect storage.

        async def generate(self, question, chunks, history):
            await asyncio.sleep(0.01)
            index = int(question)
            return ChatAnswer(f"Answer [{index + 1}]", [index], self.model_name)

        def generate_stream(self, *args):
            raise AssertionError("legacy shared-state stream was used")

    app.state.guguta_chat._provider = Provider()

    async def send(index):
        session = await client.post(
            f"/api/v1/notebooks/{nb}/sessions",
            json={"title": "Concurrent"},
            cookies=_cookies(a["auth"]),
            headers=_headers(a["auth"]),
        )
        path = f"/api/v1/notebooks/{nb}/sessions/{session.json()['id']}/messages"
        response = await client.post(
            path + "/stream",
            json={"content": str(index)},
            cookies=_cookies(a["auth"]),
            headers=_headers(a["auth"]),
        )
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert not any(e["event"] == "error" for e in events), events
        done = next(e for e in events if e["event"] == "done")
        citations = await client.get(
            path + f"/{done['assistant_message_id']}/citations",
            cookies=_cookies(a["auth"]),
        )
        assert len(citations.json()) == done["cited"] == 1

    await asyncio.gather(send(0), send(1))


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_saved_citation_order_and_usage(client, worker, migrator_engine, streaming):
    from dataclasses import replace

    from open_notebook.ai.guguta.chat import ChatAnswer

    a = await _setup_notebook_with_pdf(
        client, worker, "Ordinals " + uuid.uuid4().hex[:8], "Synthetic ordered evidence."
    )
    nb = a["notebook"]["id"]
    app = client._transport.app
    me = await client.get("/api/v1/auth/me", cookies=_cookies(a["auth"]))
    chunk = (await app.state.guguta_search.search_notebook(
        uuid.UUID(me.json()["id"]), uuid.UUID(nb), "pagina PDF 1"
    ))[0]
    context = [replace(chunk, locator={"page":2}), chunk,
               replace(chunk, locator={"page":9})]

    async def retrieve(*args):
        return context

    class Provider:
        model_name = "synthetic-ordered"

        async def generate(self, *args):
            # Context indexes are sparse and reversed; visible citations are
            # dense and index the saved list, NOT the hidden context.
            return ChatAnswer("Later [1], earlier [2]", [2,0], self.model_name,
                              123,456,0.2,"synthetic-version")

    app.state.guguta_chat._retrieve = retrieve
    app.state.guguta_chat._provider = Provider()
    session = (await client.post(
        f"/api/v1/notebooks/{nb}/sessions", json={"title":"Ordered"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )).json()
    path = f"/api/v1/notebooks/{nb}/sessions/{session['id']}/messages"
    response = await client.post(
        path + ("/stream" if streaming else ""), json={"content":"Synthetic question"},
        cookies=_cookies(a["auth"]), headers=_headers(a["auth"]),
    )
    assert response.status_code == 200
    if streaming:
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ")]
        assert not any(e["event"] == "error" for e in events)
        message_id = next(e["assistant_message_id"] for e in events if e["event"] == "done")
    else:
        message_id = response.json()["assistant_message_id"]
    with migrator_engine.begin() as conn:
        usage = conn.execute(text(
            "SELECT prompt_tokens,completion_tokens,total_tokens,estimated_cost "
            "FROM chat_messages WHERE id=:id"
        ), {"id":uuid.UUID(message_id)}).one()
        assert usage[:3] == (123,456,579)
        assert float(usage[3]) == pytest.approx(0.2)
        # Deliberately reverse timestamp ordering: the persisted citation
        # ordinal must still determine which page is [1] and which is [2].
        conn.execute(text(
            "UPDATE citations SET created_at=CASE WHEN locator->>'citation_number'='1' "
            "THEN '2001-01-01'::timestamptz ELSE '2000-01-01'::timestamptz END "
            "WHERE message_id=:id"
        ), {"id":uuid.UUID(message_id)})
    citations = (await client.get(path+f"/{message_id}/citations",
                                 cookies=_cookies(a["auth"]))).json()
    assert [(c["locator"]["citation_number"],c["locator"]["page"])
            for c in citations] == [(1,9),(2,2)]
