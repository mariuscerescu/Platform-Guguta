"""Agent regressions: original pixels, follow-ups, scope and bounded execution."""

import asyncio
import base64
import io
import json
import uuid
from dataclasses import replace

import httpx
import pytest
from PIL import Image

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
    message = {"role": "assistant", "content": None}
    if name:
        message["tool_calls"] = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args or {})},
            }
        ]
    return {"message": message, "usage": (12, 3, 0.001)}


@pytest.mark.asyncio
async def test_followup_reopens_original_page_and_accounts_for_agent_calls():
    item = chunk()
    search = Search(item)
    calls = []

    class Provider:
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
    service = ChatService(None, search, Provider())
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
        assert body["provider"] == {"require_parameters": True}
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
