"""Authenticated voice providers, CSRF-protected sessions and notebook context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from api.routers.guguta_v1 import get_actor
from api.services.guguta.openai_live_voice import MAX_SDP_LENGTH


class VoiceOption(BaseModel):
    id: str | None = Field(default=None, max_length=100)
    text: str = Field(max_length=1500)


class VoiceCard(BaseModel):
    # Intentionally no answer/back/solution fields in the voice contract.
    question: str = Field(max_length=3000)


class VoiceQuestion(BaseModel):
    prompt: str = Field(max_length=3000)
    options: list[Annotated[str, Field(max_length=1500)] | VoiceOption] = Field(
        default_factory=list, max_length=12
    )
    questionType: str | None = Field(default=None, max_length=80)


class VoiceContext(BaseModel):
    notebookId: uuid.UUID | None = None
    quizId: str | None = Field(default=None, max_length=128)
    lessonId: str | None = Field(default=None, max_length=128)
    lessonTitle: str | None = Field(default=None, max_length=500)
    subjectLabel: str | None = Field(default=None, max_length=120)
    grade: Annotated[str, Field(max_length=40)] | int | None = None
    locale: str | None = Field(default=None, max_length=20)
    selectedSourceIds: list[uuid.UUID] | None = Field(default=None, max_length=200)
    activeCard: VoiceCard | None = None
    activeQuestion: VoiceQuestion | None = None


class VoiceSessionRequest(BaseModel):
    context: VoiceContext = Field(default_factory=VoiceContext)


class VoiceContextRequest(VoiceSessionRequest):
    query: str | None = Field(default=None, max_length=1000)


class OpenAIVoiceSessionRequest(VoiceSessionRequest):
    model_config = ConfigDict(extra="forbid")
    sdp: str = Field(min_length=1, max_length=MAX_SDP_LENGTH)


voice_router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@voice_router.get("/providers")
async def voice_providers(request: Request, response: Response) -> dict:
    get_actor(request)
    response.headers["Cache-Control"] = "no-store"
    return {
        "providers": [
            {"id": "elevenlabs", "configured": request.app.state.guguta_voice.configured},
            {"id": "openai", "configured": request.app.state.guguta_openai_voice.configured},
        ],
        "defaultProvider": "elevenlabs",
    }


@voice_router.post("/elevenlabs/session")
async def start_voice_session(
    body: VoiceSessionRequest, request: Request, response: Response
) -> dict:
    actor = get_actor(request)
    response.headers["Cache-Control"] = "no-store"
    return await request.app.state.guguta_voice.create_session(
        actor, body.context.model_dump(exclude_none=True)
    )


@voice_router.post("/elevenlabs/context")
async def voice_context(
    body: VoiceContextRequest, request: Request, response: Response
) -> dict[str, str]:
    actor = get_actor(request)
    response.headers["Cache-Control"] = "no-store"
    return {
        "contextText": await request.app.state.guguta_voice.context(
            actor, body.context.model_dump(exclude_none=True), query=body.query
        )
    }


@voice_router.post("/openai/session")
async def start_openai_voice_session(
    body: OpenAIVoiceSessionRequest, request: Request, response: Response
) -> dict:
    actor = get_actor(request)
    response.headers["Cache-Control"] = "no-store"
    return await request.app.state.guguta_openai_voice.create_session(
        actor, body.context.model_dump(exclude_none=True), body.sdp
    )


@voice_router.post("/openai/context")
async def openai_voice_context(
    body: VoiceContextRequest, request: Request, response: Response
) -> dict[str, str]:
    actor = get_actor(request)
    response.headers["Cache-Control"] = "no-store"
    return {
        "contextText": await request.app.state.guguta_openai_voice.context(
            actor, body.context.model_dump(exclude_none=True), query=body.query
        )
    }
