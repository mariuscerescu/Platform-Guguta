"""Direct Gemini contracts: no network, real prompts, synthetic credentials."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from api.services.guguta.chat_agent import NotebookChatAgent
from open_notebook.ai.guguta.audio_overview import AudioScriptGenerator
from open_notebook.ai.guguta.chat import get_chat_provider
from open_notebook.ai.guguta.flashcards import FlashcardGenerator
from open_notebook.ai.guguta.gemini import GeminiChatProvider, GeminiClient
from open_notebook.ai.guguta.openrouter import OpenRouterError
from open_notebook.ai.guguta.quizzes import QuizGenerator
from open_notebook.database.guguta.config import GugutaConfig


def config(**kwargs):
    return GugutaConfig(_env_file=None, chat_provider="gemini",
                        gemini_api_key="synthetic-google-key", **kwargs)


def completion(content):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]}


def test_gemini_requires_its_own_key_and_resources_use_selected_provider():
    with pytest.raises(ValidationError, match="GUGUTA_GEMINI_API_KEY"):
        GugutaConfig(_env_file=None, chat_provider="gemini", gemini_api_key="")
    cfg = config()
    assert cfg.gemini_thinking_level == "medium"
    assert isinstance(get_chat_provider("gemini", cfg), GeminiChatProvider)
    for factory in (QuizGenerator, FlashcardGenerator, AudioScriptGenerator):
        generator = factory(cfg)
        assert isinstance(generator._client, GeminiClient)
        assert generator._model == "gemini-3.8-flash"


@pytest.mark.asyncio
async def test_direct_endpoint_medium_and_no_openrouter_routing_or_small_thinking_budget():
    def respond(request):
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-google-key"
        body = json.loads(request.content)
        assert body["model"] == "gemini-3.8-flash"
        assert body["max_tokens"] == 16384
        assert body["extra_body"]["google"]["thinking_config"] == {
            "thinking_level": "medium", "include_thoughts": False,
        }
        assert not {"provider", "reasoning", "models", "temperature", "top_p", "top_k"} & body.keys()
        return httpx.Response(200, json=completion({"queries": ["fracții"]}))
    provider = GeminiChatProvider(config(), transport=httpx.MockTransport(respond))
    assert await provider.plan_queries("Ce este o fracție?", []) == ["fracții"]


@pytest.mark.asyncio
async def test_source_images_and_dense_citations_keep_existing_contract():
    def respond(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        assert body["messages"][-1]["content"][-1]["image_url"]["url"].startswith("data:image/")
        return httpx.Response(200, json=completion({"paragraphs": [
            {"text": "Definiția din manual.", "source_ids": ["F1"]},
        ]}))
    provider = GeminiChatProvider(config(), transport=httpx.MockTransport(respond))
    answer = await provider.generate("Explică definiția", [SimpleNamespace(
        text="Definiție", image_url="data:image/png;base64,c3ludGhldGlj", locator={"page": 1},
    )], [])
    assert answer.model == "gemini-3.8-flash"
    assert answer.cited == [0] and answer.content == "Definiția din manual. [1]"


@pytest.mark.asyncio
async def test_tool_signatures_survive_roundtrip_without_thought_text():
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
                "reasoning": "Never expose this thought text", "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "list_sources", "arguments": "{}"},
                    "extra_content": {"google": {"thought_signature": "opaque-signature"}},
                }],
            }}]})
        tool = calls[-1]["messages"][-2]["tool_calls"][0]
        assert tool["extra_content"]["google"]["thought_signature"] == "opaque-signature"
        assert "Never expose" not in json.dumps(calls[-1])
        return httpx.Response(200, json=completion({}))
    provider = GeminiChatProvider(config(), transport=httpx.MockTransport(respond))
    history = [{"role": "user", "content": "Manualele mele"}]
    turn = await provider.choose_tools(history, [])
    await provider.choose_tools([*history, turn["message"],
        {"role": "tool", "tool_call_id": "call-1", "content": "{}"}], [])


@pytest.mark.asyncio
async def test_agent_replays_exact_tool_inputs_with_google_signature():
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
                "tool_calls": [{"id": "call-1", "type": "function", "function": {
                    "name": "list_sources", "arguments": "{}"},
                    "extra_content": {"google": {"thought_signature": "opaque-signature"}},
                }],
            }}]})
        original = requests[0]["messages"]
        assert body["messages"][:len(original)] == original
        call = body["messages"][len(original)]["tool_calls"][0]
        assert call["extra_content"]["google"]["thought_signature"] == "opaque-signature"
        assert body["messages"][len(original) + 1]["role"] == "tool"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "GATA"}}]})

    search = SimpleNamespace(context_revision=AsyncMock(return_value=1),
                             authorize_chunks=AsyncMock(return_value=[]),
                             list_sources=AsyncMock(return_value=[]))
    provider = GeminiChatProvider(config(), transport=httpx.MockTransport(respond))
    result = await NotebookChatAgent(search, None).retrieve(
        uuid.uuid4(), uuid.uuid4(), provider, "Ce manuale am?", [], [],
    )
    assert len(requests) == 2
    assert result.trace == [{"tool": "list_sources", "status": "ok"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 500])
async def test_google_failures_never_expose_key_or_provider_body(status):
    client = GeminiClient(config(), transport=httpx.MockTransport(lambda request:
        httpx.Response(status, json={"error": {"message": "synthetic-google-key SECRET DOCUMENT"}},
                       headers={"Location": "https://example.com"})))
    with pytest.raises(OpenRouterError) as err:
        await client.post("chat/completions", {"messages": []})
    assert "synthetic-google-key" not in str(err.value) and "SECRET DOCUMENT" not in str(err.value)
    assert "Gemini" in str(err.value)


@pytest.mark.asyncio
async def test_google_internal_failure_retries_once_but_invalid_request_does_not():
    for status, expected_calls in [(500, 2), (400, 1)]:
        calls = []

        def respond(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(status, json={"error": {"message": "PRIVATE PROVIDER DETAILS"}})
            return httpx.Response(200, json={"choices": []})

        client = GeminiClient(config(), transport=httpx.MockTransport(respond))
        if status == 500:
            assert await client.post("chat/completions", {"messages": []}) == {"choices": []}
        else:
            with pytest.raises(OpenRouterError, match="Gemini"):
                await client.post("chat/completions", {"messages": []})
        assert len(calls) == expected_calls
