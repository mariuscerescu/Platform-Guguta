"""Short greetings avoid research; lesson requests still acquire evidence."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from api.services.guguta.chat import ChatService, ChatSessionNotFound
from api.services.guguta.chat_agent import NotebookChatAgent
from open_notebook.ai.guguta.chat import ChatAnswer
from tests.guguta.test_chat_agent import Pdf, Search, chunk, turn


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["Salut", "Salut Guguță!", "Bună, Guguță!", "Bună ziua!", "hello"])
async def test_greeting_avoids_sources_tools_and_paid_model(question):
    search = SimpleNamespace(context_revision=AsyncMock(return_value=1),
                             list_sources=AsyncMock(), search_notebook=AsyncMock())
    provider = SimpleNamespace(generate=AsyncMock(), plan_queries=AsyncMock())
    service = ChatService(Mock(spec=AsyncEngine), search, provider)
    actor, notebook = uuid.uuid4(), uuid.uuid4()
    assert await service._retrieve(actor, notebook, question, []) == []
    answer, context = await service._answer(actor, notebook, question, [], [])
    assert answer.model == "guguta-greeting" and answer.cited == [] and context == []
    assert answer.prompt_tokens == answer.completion_tokens == 0
    search.list_sources.assert_not_awaited()
    search.search_notebook.assert_not_awaited()
    provider.generate.assert_not_awaited()
    provider.plan_queries.assert_not_awaited()


@pytest.mark.asyncio
async def test_greeting_still_checks_notebook_access():
    service = ChatService(Mock(spec=AsyncEngine),
                          SimpleNamespace(context_revision=AsyncMock(return_value=None)), Mock())
    with pytest.raises(ChatSessionNotFound):
        await service._answer(uuid.uuid4(), uuid.uuid4(), "Salut", [], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("with_attachment", [False, True])
async def test_question_or_new_attachment_is_never_treated_as_simple_greeting(with_attachment):
    search = SimpleNamespace(context_revision=AsyncMock(return_value=1),
                             list_sources=AsyncMock(return_value=[]),
                             attachment_context=AsyncMock(return_value=[]))
    provider = SimpleNamespace(generate=AsyncMock(return_value=ChatAnswer("Explicație", [], "synthetic")))
    service = ChatService(Mock(spec=AsyncEngine), search, provider)
    if with_attachment:
        service._attachment_ids = [uuid.uuid4()]
    question = "Salut" if with_attachment else "Salut! Lecția despre deep learning."
    answer, _ = await service._answer(uuid.uuid4(), uuid.uuid4(), question, [], [])
    assert answer.model == "synthetic"
    provider.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_can_search_from_authorized_catalog_without_listing_again():
    item = chunk()
    search = Search(item)
    catalog = [{"source_id": str(item.notebook_source_id), "name": "Lecție Deep Learning"}]
    calls = []

    class Provider:
        async def choose_tools(self, messages, tools):
            payload = json.loads(messages[-1]["content"][0]["text"])
            calls.append(payload)
            if len(calls) == 1:
                assert payload["untrusted_available_sources"] == catalog
                return turn("search_pages", {"query": "deep learning"})
            assert payload["untrusted_evidence"]
            return turn()

    result = await NotebookChatAgent(search, Pdf()).retrieve(
        uuid.uuid4(), uuid.uuid4(), Provider(), "Lecția despre deep learning", [], [],
        available_sources=catalog,
    )
    assert result.trace == [{"tool": "search_pages", "status": "ok"}]
    assert len(calls) == 2 and result.chunks
