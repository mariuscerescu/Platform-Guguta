from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import Request, Response
from pydantic import ValidationError

from api.routers.guguta_voice import (
    OpenAIVoiceSessionRequest,
    VoiceContext,
    VoiceContextRequest,
    openai_voice_context,
    start_openai_voice_session,
    voice_providers,
)
from api.services.guguta.openai_live_voice import MAX_SDP_LENGTH, OpenAILiveVoiceService
from api.services.guguta.openai_voice_profile import VOICE_PROMPT
from api.services.guguta.voice import VoiceRateLimited, VoiceService, VoiceUnavailable
from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.exceptions import AuthenticationError, InvalidInputError, NotFoundError

OFFER = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
ANSWER = "v=0\r\no=- 2 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
ACTOR = ActorContext(uuid.uuid4(), "Elev")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-project-key")
    monkeypatch.setenv("GUGUTA_OPENAI_API_KEY", "test-dedicated-key")
    monkeypatch.setenv("GUGUTA_OPENAI_VOICE_ID", "voice_guguta_test")


def context_service():
    service = Mock(spec=VoiceService)
    service.context = AsyncMock(return_value="Doar fragmentele autorizate ale carnetului.")
    return service


@pytest.mark.asyncio
async def test_session_authorizes_context_first_and_returns_only_webrtc_answer(configured):
    context = {"notebookId": uuid.uuid4(), "selectedSourceIds": [uuid.uuid4()]}
    evidence = context_service()
    requests = []

    async def handler(request):
        evidence.context.assert_awaited_once_with(ACTOR, context, query=None)
        requests.append(request)
        assert request.url == "https://api.openai.com/v1/live/sessions"
        assert request.headers["authorization"] == "Bearer test-dedicated-key"
        payload = json.loads(request.content)
        assert payload["transport"] == {"type": "webrtc", "sdp": OFFER}
        session = payload["session"]
        assert session["model"] == "gpt-live-1"
        assert session["audio"]["output"]["voice"] == {"id": "voice_guguta_test"}
        assert session["store"] is False
        assert session["delegation"] == {"type": "client"}
        assert VOICE_PROMPT in session["instructions"]
        assert session["input"][0]["role"] == "developer"
        assert "fragmentele autorizate" in session["input"][0]["content"][0]["text"]
        return httpx.Response(201, json={
            "session": {"id": "opaque_live_test", "secret": "not-for-browser"},
            "transport": {"type": "webrtc", "sdp": ANSWER},
            "api_key": "not-for-browser",
        })

    service = OpenAILiveVoiceService(evidence, transport=httpx.MockTransport(handler))
    assert service.configured
    assert await service.create_session(ACTOR, context, OFFER) == {
        "session": {"id": "opaque_live_test"},
        "transport": {"type": "webrtc", "sdp": ANSWER},
    }
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_unauthorized_notebook_never_creates_a_paid_session(configured):
    evidence = context_service()
    denied = NotFoundError("notebook unavailable")
    evidence.context.side_effect = denied
    provider = Mock(side_effect=AssertionError("Provider must not be called"))
    service = OpenAILiveVoiceService(evidence, transport=httpx.MockTransport(provider))
    with pytest.raises(NotFoundError) as error:
        await service.create_session(ACTOR, {"notebookId": uuid.uuid4()}, OFFER)
    assert error.value is denied
    provider.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["key", "voice", "invalid_voice"])
async def test_incomplete_configuration_never_calls_provider(configured, monkeypatch, missing):
    if missing == "key":
        monkeypatch.delenv("OPENAI_API_KEY")
        monkeypatch.delenv("GUGUTA_OPENAI_API_KEY")
    else:
        monkeypatch.setenv("GUGUTA_OPENAI_VOICE_ID", "marin" if missing == "invalid_voice" else "")
    evidence = context_service()
    provider = Mock(side_effect=AssertionError("Provider must not be called"))
    service = OpenAILiveVoiceService(evidence, transport=httpx.MockTransport(provider))
    assert not service.configured
    with pytest.raises(VoiceUnavailable, match="nu este configurată"):
        await service.create_session(ACTOR, {}, OFFER)
    provider.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_upstream_errors_are_sanitized_without_retries(configured, status, caplog):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "private-provider-detail test-dedicated-key"})

    service = OpenAILiveVoiceService(context_service(), transport=httpx.MockTransport(handler))
    expected = VoiceRateLimited if status == 429 else VoiceUnavailable
    with pytest.raises(expected) as error:
        await service.create_session(ACTOR, {}, OFFER)
    assert "private-provider-detail" not in str(error.value) + caplog.text
    assert "test-dedicated-key" not in str(error.value) + caplog.text
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    [],
    {"session": {"id": "live_test"}, "transport": {"type": "sip"}},
    {"session": {"id": ""}, "transport": {"type": "webrtc", "sdp": ANSWER}},
    {"session": {"id": "live_test"}, "transport": {"type": "webrtc", "sdp": "not-sdp"}},
])
async def test_malformed_upstream_response_is_not_returned(configured, payload):
    service = OpenAILiveVoiceService(
        context_service(), transport=httpx.MockTransport(lambda _: httpx.Response(201, json=payload))
    )
    with pytest.raises(VoiceUnavailable):
        await service.create_session(ACTOR, {}, OFFER)


@pytest.mark.asyncio
async def test_provider_timeout_is_sanitized(configured):
    def handler(request):
        raise httpx.ReadTimeout("private-provider-detail", request=request)

    service = OpenAILiveVoiceService(context_service(), transport=httpx.MockTransport(handler))
    with pytest.raises(VoiceUnavailable) as error:
        await service.create_session(ACTOR, {}, OFFER)
    assert "private-provider-detail" not in str(error.value)


@pytest.mark.asyncio
async def test_bad_sdp_is_rejected_before_context_or_provider(configured):
    evidence = context_service()
    provider = Mock(side_effect=AssertionError("Provider must not be called"))
    service = OpenAILiveVoiceService(evidence, transport=httpx.MockTransport(provider))
    for sdp in [" ", "v=0" + "x" * MAX_SDP_LENGTH, "v=0\x00"]:
        with pytest.raises(InvalidInputError):
            await service.create_session(ACTOR, {}, sdp)
    evidence.context.assert_not_awaited()
    provider.assert_not_called()


def request_for(service, *, authenticated=True):
    state = SimpleNamespace(guguta_openai_voice=service, guguta_voice=SimpleNamespace(configured=True))
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})
    if authenticated:
        request.state.guguta_actor = ACTOR
    return request


@pytest.mark.asyncio
async def test_routes_require_actor_and_provider_metadata_has_no_secrets():
    service = SimpleNamespace(configured=False, create_session=AsyncMock(), context=AsyncMock())
    anonymous = request_for(service, authenticated=False)
    with pytest.raises(AuthenticationError):
        await voice_providers(anonymous, Response())
    with pytest.raises(AuthenticationError):
        await start_openai_voice_session(OpenAIVoiceSessionRequest(sdp=OFFER), anonymous, Response())
    with pytest.raises(AuthenticationError):
        await openai_voice_context(VoiceContextRequest(), anonymous, Response())
    service.create_session.assert_not_awaited()
    service.context.assert_not_awaited()

    response = Response()
    result = await voice_providers(request_for(service), response)
    assert result == {"providers": [
        {"id": "elevenlabs", "configured": True},
        {"id": "openai", "configured": False},
    ], "defaultProvider": "elevenlabs"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_context_route_preserves_actor_and_source_scope():
    evidence = context_service()
    service = OpenAILiveVoiceService(evidence)
    context = VoiceContext(notebookId=uuid.uuid4(), selectedSourceIds=[uuid.uuid4()])
    response = Response()
    result = await openai_voice_context(
        VoiceContextRequest(context=context, query="Ce spune pagina 5?"),
        request_for(service), response,
    )
    evidence.context.assert_awaited_once_with(
        ACTOR, context.model_dump(exclude_none=True), query="Ce spune pagina 5?"
    )
    assert result == {"contextText": evidence.context.return_value}
    assert response.headers["cache-control"] == "no-store"


def test_browser_cannot_select_provider_model_voice_or_endpoint():
    for field in ["model", "voice", "endpoint", "api_key"]:
        with pytest.raises(ValidationError):
            OpenAIVoiceSessionRequest.model_validate({"sdp": OFFER, field: "browser-controlled"})
    with pytest.raises(ValidationError):
        OpenAIVoiceSessionRequest(sdp="v=0" + "x" * MAX_SDP_LENGTH)
