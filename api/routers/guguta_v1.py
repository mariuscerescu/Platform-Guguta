"""Guguță API routers: /api/v1 — auth (sessions) and notebooks CRUD.

Routers stay thin; logic lives in services. Errors are typed domain
exceptions mapped by the app factory to contract status codes (GHID §5.1).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from open_notebook.auth.guguta.actor import ActorContext, ActorDenied
from open_notebook.auth.guguta.sessions import (
    CSRF_HEADER,
    SESSION_COOKIE,
    SessionService,
)
from open_notebook.exceptions import AuthenticationError, InvalidInputError


def get_session_service(request: Request) -> SessionService:
    return request.app.state.guguta_sessions  # type: ignore[attr-defined]


def get_actor(request: Request) -> ActorContext:
    actor: Optional[ActorContext] = getattr(request.state, "guguta_actor", None)
    if actor is None:
        raise AuthenticationError("Autentificare necesară.")
    return actor


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    args = SessionService.cookie_args(request.app.state.guguta_config.public_origin)
    response.set_cookie(value=token, max_age=None, **args)


def clear_session_cookie(response: Response, request: Request) -> None:
    args = SessionService.cookie_args(request.app.state.guguta_config.public_origin)
    response.delete_cookie(**args)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class DevLoginRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)


class MeResponse(BaseModel):
    id: str
    display_name: str
    roles: list[str]


auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@auth_router.post("/dev-login")
async def dev_login(body: DevLoginRequest, request: Request, response: Response) -> MeResponse:
    """Synthetic login — ONLY in development/ci with auth_mode=test.

    Provisions (issuer='test', subject=name) through the SECURITY DEFINER
    function and opens a session. The startup configuration refuses test auth
    outside development; this route additionally refuses at request time
    (defence in depth).
    """
    config = request.app.state.guguta_config
    if config.auth_mode != "test" or config.environment not in ("development", "ci"):
        raise ActorDenied("Login-ul sintetic este dezactivat.")
    engine = request.app.state.guguta_engine
    sessions: SessionService = get_session_service(request)
    name = body.display_name.strip()
    if not name:
        raise InvalidInputError("Numele este obligatoriu.")
    from sqlalchemy import text

    async with engine.begin() as conn:
        user_id = (
            await conn.execute(
                text("SELECT guguta_provision_user(:issuer, :subject, :name)"),
                {"issuer": "test", "subject": name, "name": name},
            )
        ).scalar_one()
    token, csrf = await sessions.create_session(user_id)
    set_session_cookie(response, request, token)
    response.headers[CSRF_HEADER] = csrf
    return MeResponse(id=str(user_id), display_name=name, roles=["user"])


@auth_router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, Any]:
    sessions: SessionService = get_session_service(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await sessions.revoke(token)
    clear_session_cookie(response, request)
    return {"ok": True}


@auth_router.get("/me")
async def me(request: Request) -> MeResponse:
    actor = get_actor(request)
    return MeResponse(
        id=str(actor.actor_id), display_name=actor.display_name,
        roles=sorted(actor.roles),
    )


# ---------------------------------------------------------------------------
# Notebooks
# ---------------------------------------------------------------------------


class NotebookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    # origin is server-decided; a client-supplied origin is ignored.


class NotebookUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    archive: Optional[bool] = None


notebooks_router = APIRouter(prefix="/api/v1/notebooks", tags=["notebooks"])


@notebooks_router.post("", status_code=201)
async def create_notebook(body: NotebookCreate, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    return await service.create(actor, title=body.title, description=body.description)


@notebooks_router.get("")
async def list_notebooks(
    request: Request, page: int = 1, page_size: int = 20,
    sort: str = "created_desc", status: Optional[str] = None,
) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    if sort not in ("created_desc", "created_asc", "title_asc", "title_desc", "updated_desc"):
        raise InvalidInputError("Sortare neacceptată.")
    if status not in (None, "active", "archived"):
        raise InvalidInputError("Stare neacceptată.")
    return await service.list_for_actor(
        actor, page=page, page_size=page_size,
        sort=sort,  # type: ignore[arg-type]
        status=status,
    )


@notebooks_router.get("/{notebook_id}")
async def get_notebook(notebook_id: uuid.UUID, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    return await service.get(actor, notebook_id)


@notebooks_router.patch("/{notebook_id}")
async def update_notebook(
    notebook_id: uuid.UUID, body: NotebookUpdate, request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    return await service.update(
        actor, notebook_id,
        title=body.title, description=body.description, archive=body.archive,
    )


@notebooks_router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: uuid.UUID, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    deleted = await service.delete(actor, notebook_id)
    if not deleted:
        # Foreign or already-deleted object: 404, no existence disclosure.
        from api.services.guguta.notebooks import NotebookNotFound

        raise NotebookNotFound()
    return {"deleted": True}
