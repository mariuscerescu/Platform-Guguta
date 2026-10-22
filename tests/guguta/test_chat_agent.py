"""Agent regressions: original pixels, follow-ups, scope and bounded execution."""

import asyncio
import base64
import io
import json
import uuid
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine

from api.services.guguta.chat import ChatService
from api.services.guguta.chat_agent import NotebookChatAgent
from api.services.guguta.search import RetrievedChunk
from open_notebook.ai.guguta.chat import ChatAnswer
from open_notebook.ai.guguta.openrouter import OpenRouterChatProvider, OpenRouterError
from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.exceptions import ExternalServiceError


def chunk(page=13, source=None):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 60), "red").save(buffer, "PNG")
    return RetrievedChunk(
        uuid.uuid4(),
        "Synthetic diagram with no object count in OCR.",
        {"page": page, "printed_page": 37},
        source or uuid.uuid4(),
        uuid.uuid4(),
        "Synthetic manual.pdf",
        1.0,
        "locator",
        "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
    )


class Search:
    def __init__(self, item):
        self.item = item
        self.opens = []
        self.allowed = True

    async def context_revision(self, *args):
        return 1 if self.allowed else 2

    async def open_page(self, actor, notebook, source, page, **kwargs):
        self.opens.append((source, page, kwargs))
        if (
            self.allowed
            and source == self.item.notebook_source_id
            and page == self.item.locator["page"]
        ):
            return [self.item]
        return []

    async def authorize_chunks(self, actor, notebook, chunks):
        return [
            c
            for c in chunks
            if self.allowed and c.notebook_source_id == self.item.notebook_source_id
        ]

    async def list_sources(self, *args):
        return (
            [
                {
                    "source_id": str(self.item.notebook_source_id),
                    "name": self.item.local_name,
                }
            ]
            if self.allowed
            else []
        )

    async def search_notebook(self, *args, **kwargs):
        return [replace(self.item, image_url=None)] if self.allowed else []


class Pdf:
    async def enrich(self, actor, notebook, chunks):
        return chunks

    async def crop(self, actor, notebook, chunk, region):
        if region[0] >= region[2] or region[1] >= region[3]:
            raise ValueError("invalid crop")
        return replace(chunk, locator={**chunk.locator, "image_region": list(region)})


def turn(name=None, args=None, index=1):
    message: dict[str, object] = {"role": "assistant", "content": None}
    if name:
        message["tool_calls"] = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args or {})},
            }
        ]
    return {"message": message, "usage": (12, 3, 0.001)}


class NonStreamingProvider:
    model_name = "synthetic"

    def generate_stream(self, *args, **kwargs):
        raise AssertionError("agent tests must not use the legacy streaming path")


@pytest.mark.asyncio
async def test_followup_reopens_original_page_and_accounts_for_agent_calls():
    item = chunk()
    search = Search(item)
    calls = []

    class Provider(NonStreamingProvider):
        model_name = "synthetic-vision"

        async def choose_tools(self, messages, tools):
            calls.append(messages)
            assert {t["function"]["name"] for t in tools} == {
                "list_sources",
                "search_pages",
                "open_page",
                "load_image",
                "crop_image",
            }
            pixels = [p for p in messages[-1]["content"] if p["type"] == "image_url"]
            assert pixels[0]["image_url"]["url"] == item.image_url
            return turn()

        async def generate(self, question, chunks, history):
            assert question == "How many objects are there?"
            assert chunks[0].locator["page"] == 13
            assert chunks[0].image_url == item.image_url
            return ChatAnswer("Five objects. [1]", [0], self.model_name, 40, 6, 0.002)

    history = [
        {
            "role": "assistant",
            "content": "An incorrect prior count: 99.",
            "source_refs": [
                {
                    "source_id": str(item.notebook_source_id),
                    "material_version_id": str(item.material_version_id),
                    "locator": item.locator,
                }
            ],
        }
    ]
    service = ChatService(Mock(spec=AsyncEngine), search, Provider())
    service._agent = NotebookChatAgent(search, Pdf())
    answer, context = await service._answer(
        uuid.uuid4(), uuid.uuid4(), "How many objects are there?", [], history
    )
    assert search.opens == [(item.notebook_source_id, 13, {})]
    assert answer.cited == [0] and context[0].chunk_id == item.chunk_id
    assert answer.prompt_tokens == 52 and answer.completion_tokens == 9
    assert answer.estimated_cost == 0.003
    assert answer.prompt_version.endswith("-agent-1")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_agent_searches_loads_and_crops_actual_pixels():
    item = chunk()
    search = Search(item)
    observed = []

    class Provider:
        async def choose_tools(self, messages, tools):
            observed.append(messages)
            step = len(observed)
            if step == 1:
                return turn("search_pages", {"query": "diagrams"}, step)
            if step == 2:
                assert not any(
                    c["type"] == "image_url" for c in messages[-1]["content"]
                )
                return turn("load_image", {"image_id": "F1"}, step)
            if step == 3:
                assert any(c["type"] == "image_url" for c in messages[-1]["content"])
                return turn(
                    "crop_image",
                    {
                        "image_id": "F1",
                        "left": 0.1,
                        "top": 0.2,
                        "right": 0.9,
                        "bottom": 0.8,
                    },
                    step,
                )
            assert (
                len([c for c in messages[-1]["content"] if c["type"] == "image_url"])
                == 2
            )
            return turn()

    result = await NotebookChatAgent(search, Pdf()).retrieve(
        uuid.uuid4(), uuid.uuid4(), Provider(), "Read this diagram", [], []
    )
    assert [t["tool"] for t in result.trace] == [
        "search_pages",
        "load_image",
        "crop_image",
    ]
    assert result.chunks[0].chunk_id == result.chunks[1].chunk_id == item.chunk_id
    assert result.chunks[1].locator["image_region"] == [0.1, 0.2, 0.9, 0.8]


@pytest.mark.asyncio
async def test_invalid_unknown_and_duplicate_tools_cannot_run_forever():
    item = chunk()
    calls = 0

    class Provider:
        async def choose_tools(self, *args):
            nonlocal calls
            calls += 1
            return turn(
                "crop_image",
                {
                    "image_id": "F1",
                    "left": 0.9,
                    "top": 0.0,
                    "right": 0.1,
                    "bottom": 1.0,
                },
                calls,
            )

    result = await NotebookChatAgent(Search(item), Pdf(), max_rounds=3).retrieve(
        uuid.uuid4(), uuid.uuid4(), Provider(), "q", [], [item]
    )
    assert calls == 3
    assert [t["status"] for t in result.trace] == ["invalid", "duplicate", "duplicate"]
    assert len(result.chunks) == 1


@pytest.mark.asyncio
async def test_foreign_source_and_invalid_image_ids_do_not_add_evidence():
    item = chunk()
    calls = 0

    class Provider:
        async def choose_tools(self, *args):
            nonlocal calls
            calls += 1
            if calls == 1:
                return turn(
                    "open_page",
                    {"source_id": str(uuid.uuid4()), "page": 13, "page_kind": "pdf"},
                )
            if calls == 2:
                return turn("load_image", {"image_id": "F7"}, calls)
            if calls == 3:
                return turn("read_file", {"path": "/etc/passwd"}, calls)
            return turn()

    result = await NotebookChatAgent(Search(item), Pdf()).retrieve(
        uuid.uuid4(), uuid.uuid4(), Provider(), "q", [], []
    )
    assert result.chunks == []
    assert [t["status"] for t in result.trace] == ["ok", "invalid", "unknown"]


@pytest.mark.asyncio
async def test_revoked_evidence_is_removed_before_next_provider_call():
    item = chunk()
    search = Search(item)
    calls = 0

    class Provider:
        async def choose_tools(self, *args):
            nonlocal calls
            calls += 1
            search.allowed = False
            return turn()

    with pytest.raises(ExternalServiceError):
        await NotebookChatAgent(search, Pdf()).retrieve(
            uuid.uuid4(), uuid.uuid4(), Provider(), "q", [], [item]
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_changed_revision_aborts_before_sending_old_history():
    item = chunk()
    search = Search(item)
    search.allowed = False
    with pytest.raises(ExternalServiceError):
        await NotebookChatAgent(search, Pdf()).retrieve(
            uuid.uuid4(),
            uuid.uuid4(),
            object(),
            "q",
            [],
            [],
            expected_revision=1,
        )


def test_evidence_budget_counts_image_upgrades_and_crops():
    item = chunk()
    agent = NotebookChatAgent(Search(item), Pdf(), max_images=1)
    other = replace(item, chunk_id=uuid.uuid4(), image_url=None)
    merged = agent._merge([item, other], [replace(other, image_url=item.image_url)])
    assert sum(bool(c.image_url) for c in merged) == 1
    assert len(merged) == 2


@pytest.mark.asyncio
async def test_tool_adapter_uses_native_calls_and_requires_provider_support():
    item = chunk()
    requests = []

    def response(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["provider"] == {
            "require_parameters": True, "sort": "latency",
            "data_collection": "deny", "zdr": True,
            "preferred_max_latency": 3, "preferred_min_throughput": 50,
        }
        assert body["tool_choice"] == "auto" and body["tools"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": turn("list_sources")["message"],
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "cost": 0},
            },
        )

    provider = OpenRouterChatProvider(
        GugutaConfig(_env_file=None, openrouter_api_key="synthetic"),
        transport=httpx.MockTransport(response),
    )
    result = await NotebookChatAgent(Search(item), Pdf(), max_rounds=1).retrieve(
        uuid.uuid4(), uuid.uuid4(), provider, "q", [], []
    )
    assert result.trace == [{"tool": "list_sources", "status": "ok"}]
    assert result.usage == [(10, 3, 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ["[]", "null", "bad-json"])
async def test_tool_adapter_rejects_malformed_arguments(arguments):
    message = turn("open_page")["message"]
    message["tool_calls"][0]["function"]["arguments"] = arguments
    provider = OpenRouterChatProvider(
        GugutaConfig(_env_file=None, openrouter_api_key="synthetic"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"finish_reason": "tool_calls", "message": message}]},
            )
        ),
    )
    with pytest.raises(OpenRouterError):
        await provider.choose_tools(
            [], [{"type": "function", "function": {"name": "open_page"}}]
        )


@pytest.mark.asyncio
async def test_agent_timeout_cancels_the_outbound_request():
    cancelled = asyncio.Event()

    class Provider:
        async def choose_tools(self, *args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    item = chunk()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await NotebookChatAgent(Search(item), Pdf()).retrieve(
                uuid.uuid4(), uuid.uuid4(), Provider(), "q", [], []
            )
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("tight_budget", [False, True])
async def test_current_document_precedes_old_files_and_unrelated_notebook_image(tight_budget):
    note = replace(chunk(), local_name="notă medicală.png", locator={"page": 1, "image": True})
    document = replace(chunk(), local_name="fracții.docx", image_url=None,
                       locator={"paragraph": 1}, text="Lecție despre fracții.")
    exercise = replace(document, chunk_id=uuid.uuid4(), locator={"paragraph": 2},
                       text="Exercițiu: calculează 1/2 + 1/4.")
    old = replace(chunk(), local_name="lecție anterioară.txt", image_url=None)

    class AttachmentSearch(Search):
        async def list_sources(self, *args):
            return [{"source_id": str(c.notebook_source_id), "name": c.local_name,
                     "is_attachment": c is not note,
                     "mime_type": "image/png" if c is note else "text/plain"}
                    for c in [note, old, document]]

        async def attachment_context(self, actor, notebook, ids):
            assert ids == [document.notebook_source_id, old.notebook_source_id]
            # An older attachment cannot displace later chunks of the new file.
            return [document, old, exercise]

        async def authorize_chunks(self, actor, notebook, chunks):
            return chunks

    search = AttachmentSearch(note)
    turns = []

    class Provider(NonStreamingProvider):
        async def choose_tools(self, messages, tools):
            turns.append(messages)
            metadata = json.loads(messages[-1]["content"][0]["text"])["untrusted_evidence"]
            assert [c["source_scope"] for c in metadata[:2]] == ["current_attachment"] * 2
            assert all(c["source"] != note.local_name for c in metadata)
            if len(turns) == 1:
                return turn("list_sources")
            tool_result = json.loads(messages[-2]["content"])["result"]
            if isinstance(tool_result, str):
                tool_result = json.loads(tool_result)
            sources = tool_result["sources"]
            assert {s["name"]: s["source_scope"] for s in sources} == {
                note.local_name: "notebook", old.local_name: "chat_attachment",
                document.local_name: "current_attachment",
            }
            return turn()

        def generate(self, question, chunks, history):
            assert [c.text for c in chunks[:2]] == [document.text, exercise.text]
            assert all(c.notebook_source_id != note.notebook_source_id for c in chunks)
            if tight_budget:
                assert len(chunks) == 2
            else:
                assert chunks[2].source_scope == "chat_attachment"
            return ChatAnswer("Documentul conține un exercițiu despre fracții.", [0, 1], "synthetic")

    service = ChatService(Mock(spec=AsyncEngine), search, Provider())
    service._attachment_ids = [document.notebook_source_id]
    service._agent = NotebookChatAgent(search, Pdf())
    if tight_budget:
        service._max_context_chars = len(document.text) + len(exercise.text)
    history = [{"role": "assistant", "content": "O notă medicală scrisă de mână.",
                "source_refs": [{"source_id": str(note.notebook_source_id),
                                 "material_version_id": str(note.material_version_id), "locator": note.locator}]}]
    answer, _ = await service._answer(uuid.uuid4(), uuid.uuid4(), "Ajută-mă să înțeleg materialul atașat.", [], history)
    assert "fracții" in answer.content
    assert search.opens == []  # The old note is available via tools, never preloaded.


@pytest.mark.asyncio
async def test_source_priority_survives_search_and_image_tools():
    item = chunk()
    search = Search(item)
    steps = 0

    class Provider:
        async def choose_tools(self, messages, tools):
            nonlocal steps
            steps += 1
            if steps == 1:
                return turn("search_pages", {"query": "diagram"})
            evidence = json.loads(messages[-1]["content"][0]["text"])["untrusted_evidence"]
            assert evidence and all(c["source_scope"] == "current_attachment" for c in evidence)
            if steps == 2:
                return turn("load_image", {"image_id": "F1"}, steps)
            if steps == 3:
                return turn("crop_image", {"image_id": "F1", "left": 0.0, "top": 0.0,
                                           "right": 1.0, "bottom": 1.0}, steps)
            return turn()

    result = await NotebookChatAgent(search, Pdf()).retrieve(
        uuid.uuid4(), uuid.uuid4(), Provider(), "Explică imaginea atașată", [], [],
        source_scopes={item.notebook_source_id: "current_attachment"},
    )
    assert result.chunks and all(c.source_scope == "current_attachment" for c in result.chunks)
