"""Authenticated, CSRF-protected ElevenLabs sessions and notebook tool context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from api.routers.guguta_v1 import get_actor


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


voice_router = APIRouter(prefix="/api/v1/voice/elevenlabs", tags=["voice"])


@voice_router.post("/session")
async def start_voice_session(
    body: VoiceSessionRequest, request: Request, response: Response
) -> dict:
    actor = get_actor(request)
    response.headers["Cache-Control"] = "no-store"
    return await request.app.state.guguta_voice.create_session(
        actor, body.context.model_dump(exclude_none=True)
    )


@voice_router.post("/context")
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
