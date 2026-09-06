"""Guguță API routers: /api/v1 — auth (sessions) and notebooks CRUD.

Routers stay thin; logic lives in services. Errors are typed domain
exceptions mapped by the app factory to contract status codes (GHID §5.1).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
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


_STATE_COOKIE = "guguta_oidc_state"


@auth_router.get("/oidc/login", status_code=307)
async def oidc_login(request: Request, response: Response):
    """Start the OIDC Authorization Code + PKCE flow (ADR-0003).

    Only available when auth_mode=oidc and an OIDC client is configured on
    app.state (production path); dev-login remains the test-mode path.
    """
    config = request.app.state.guguta_config
    if config.auth_mode != "oidc":
        raise ActorDenied("OIDC nu este activat.")
    client = request.app.state.guguta_oidc
    url, cookie_value = client.begin_login(request.app.state.guguta_state_codec)
    response.set_cookie(
        _STATE_COOKIE, cookie_value,
        httponly=True, samesite="lax",
        secure=config.public_origin.startswith("https://"),
        max_age=600, path="/",
    )
    return RedirectResponse(url, status_code=307)


@auth_router.get("/oidc/callback")
async def oidc_callback(request: Request, response: Response, code: str = "",
                        state: str = "") -> RedirectResponse:
    """Finish the OIDC flow: validate, provision, open the session."""
    config = request.app.state.guguta_config
    if config.auth_mode != "oidc":
        raise ActorDenied("OIDC nu este activat.")
    state_cookie = request.cookies.get(_STATE_COOKIE)
    if not state_cookie:
        raise AuthenticationError("Flux OIDC pierdut (fără state).")
    client = request.app.state.guguta_oidc
    result = await client.complete_login(
        request.app.state.guguta_state_codec, state_cookie, state, code
    )
    engine = request.app.state.guguta_engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        user_id = (
            await conn.execute(
                text("SELECT guguta_provision_user(:i, :s, :n, :e)"),
                {"i": result.issuer, "s": result.subject,
                 "n": result.display_name, "e": result.email},
            )
        ).scalar_one()
    sessions: SessionService = get_session_service(request)
    token, csrf = await sessions.create_session(user_id)
    set_session_cookie(response, request, token)
    response.headers[CSRF_HEADER] = csrf
    response.delete_cookie(_STATE_COOKIE, path="/")
    return RedirectResponse("/", status_code=303)


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


# ---------------------------------------------------------------------------
# Sources (materials)
# ---------------------------------------------------------------------------

from fastapi import UploadFile  # noqa: E402


class TextSourceCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    text: str = Field(min_length=1, max_length=2_000_000)


def get_sources_service(request: Request) -> Any:
    return request.app.state.guguta_sources


sources_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/sources", tags=["sources"]
)


@sources_router.post("/file", status_code=201)
async def upload_source(
    notebook_id: uuid.UUID, request: Request, file: UploadFile
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    return await service.upload_file(
        actor, notebook_id,
        stream=file.file, original_name=file.filename, local_name=None,
    )


@sources_router.post("/text", status_code=201)
async def add_text_source(
    notebook_id: uuid.UUID, body: TextSourceCreate, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    return await service.add_text(
        actor, notebook_id, text_content=body.text, title=body.title
    )


@sources_router.get("")
async def list_sources(notebook_id: uuid.UUID, request: Request) -> list[dict[str, Any]]:
    actor = get_actor(request)
    service = get_sources_service(request)
    return await service.list_for_notebook(actor, notebook_id)


@sources_router.get("/{source_id}")
async def get_source(
    notebook_id: uuid.UUID, source_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    return await service.get(actor, notebook_id, source_id)


@sources_router.patch("/{source_id}")
async def update_source(
    notebook_id: uuid.UUID, source_id: uuid.UUID,
    body: dict[str, Any], request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    if not set(body.keys()) <= {"local_name", "selected_for_chat"}:
        from open_notebook.exceptions import InvalidInputError

        raise InvalidInputError("Câmpuri neacceptate.")
    return await service.update(
        actor, notebook_id, source_id,
        local_name=body.get("local_name"),
        selected_for_chat=body.get("selected_for_chat"),
    )


@sources_router.delete("/{source_id}")
async def delete_source(
    notebook_id: uuid.UUID, source_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    deleted = await service.delete(actor, notebook_id, source_id)
    return {"deleted": deleted}


@sources_router.get("/{source_id}/download")
async def download_source(
    notebook_id: uuid.UUID, source_id: uuid.UUID, request: Request
) -> Any:
    from fastapi.responses import Response

    actor = get_actor(request)
    service = get_sources_service(request)
    data, mime, original = await service.download(actor, notebook_id, source_id)
    headers = {"Content-Disposition": f'attachment; filename="{original or "material"}"'}
    return Response(content=data, media_type=mime, headers=headers)


@sources_router.post("/{source_id}/retry")
async def retry_source(
    notebook_id: uuid.UUID, source_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    ok = await service.retry(actor, notebook_id, source_id)
    return {"requeued": ok}


jobs_router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@jobs_router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    from open_notebook.jobs.guguta.queue import get_job_for_actor

    engine = request.app.state.guguta_engine
    job = await get_job_for_actor(engine, job_id, actor.actor_id)
    if job is None:
        from open_notebook.exceptions import NotFoundError

        raise NotFoundError()
    return job


# ---------------------------------------------------------------------------
# Search + chat (L4)
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    mode: str = Field(default="both")  # text | vector | both
    limit: int = Field(default=8, ge=1, le=50)


search_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/search", tags=["search"]
)


@search_router.post("")
async def search(
    notebook_id: uuid.UUID, body: SearchRequest, request: Request
) -> list[dict[str, Any]]:
    actor = get_actor(request)
    if body.mode not in ("text", "vector", "both"):
        from open_notebook.exceptions import InvalidInputError

        raise InvalidInputError("Mod de căutare neacceptat.")
    service = request.app.state.guguta_search
    chunks = await service.search_notebook(
        actor.actor_id, notebook_id, body.query, mode=body.mode, limit=body.limit,
    )
    return [
        {
            "chunk_id": str(c.chunk_id),
            "text": c.text,
            "locator": c.locator,
            "local_name": c.local_name,
            "score": c.score,
            "mode": c.mode,
        }
        for c in chunks
    ]


class SessionCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    idempotency_key: Optional[str] = Field(default=None, max_length=255)


chat_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/sessions", tags=["chat"]
)


@chat_router.post("", status_code=201)
async def create_session(
    notebook_id: uuid.UUID, body: SessionCreate, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_chat
    return await service.create_session(actor, notebook_id, title=body.title)


@chat_router.get("")
async def list_sessions(notebook_id: uuid.UUID, request: Request) -> list[dict[str, Any]]:
    actor = get_actor(request)
    service = request.app.state.guguta_chat
    return await service.list_sessions(actor, notebook_id)


@chat_router.get("/{session_id}/messages")
async def list_messages(
    notebook_id: uuid.UUID, session_id: uuid.UUID, request: Request
) -> list[dict[str, Any]]:
    actor = get_actor(request)
    service = request.app.state.guguta_chat
    return await service.list_messages(actor, notebook_id, session_id)


@chat_router.post("/{session_id}/messages")
async def send_message(
    notebook_id: uuid.UUID, session_id: uuid.UUID, body: MessageCreate,
    request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_chat
    return await service.send_message(
        actor, notebook_id, session_id,
        content=body.content, idempotency_key=body.idempotency_key,
    )


@chat_router.get("/{session_id}/messages/{message_id}/citations")
async def get_citations(
    notebook_id: uuid.UUID, session_id: uuid.UUID, message_id: uuid.UUID,
    request: Request,
) -> list[dict[str, Any]]:
    actor = get_actor(request)
    service = request.app.state.guguta_chat
    return await service.get_citations(actor, notebook_id, session_id, message_id)


# ---------------------------------------------------------------------------
# Notes (L5) — private, excluded from shares
# ---------------------------------------------------------------------------


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    content: Optional[str] = Field(default=None, min_length=1, max_length=100_000)


class SaveAnswerRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)


notes_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/notes", tags=["notes"]
)


def get_notes_service(request: Request) -> Any:
    return request.app.state.guguta_notes


@notes_router.post("", status_code=201)
async def create_note(
    notebook_id: uuid.UUID, body: NoteCreate, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await get_notes_service(request).create(
        actor, notebook_id, title=body.title, content=body.content
    )


@notes_router.get("")
async def list_notes(notebook_id: uuid.UUID, request: Request) -> list[dict[str, Any]]:
    actor = get_actor(request)
    return await get_notes_service(request).list_for_notebook(actor, notebook_id)


@notes_router.get("/{note_id}")
async def get_note(
    notebook_id: uuid.UUID, note_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await get_notes_service(request).get(actor, notebook_id, note_id)


@notes_router.patch("/{note_id}")
async def update_note(
    notebook_id: uuid.UUID, note_id: uuid.UUID, body: NoteUpdate, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await get_notes_service(request).update(
        actor, notebook_id, note_id, title=body.title, content=body.content
    )


@notes_router.delete("/{note_id}")
async def delete_note(
    notebook_id: uuid.UUID, note_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    deleted = await get_notes_service(request).delete(actor, notebook_id, note_id)
    return {"deleted": deleted}


@chat_router.post("/{session_id}/messages/{message_id}/save-as-note", status_code=201)
async def save_answer_as_note(
    notebook_id: uuid.UUID, session_id: uuid.UUID, message_id: uuid.UUID,
    body: SaveAnswerRequest, request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    chat = request.app.state.guguta_chat
    messages = await chat.list_messages(actor, notebook_id, session_id)
    target = next((m for m in messages if m["id"] == message_id), None)
    if target is None:
        from api.services.guguta.chat import ChatSessionNotFound

        raise ChatSessionNotFound()
    return await get_notes_service(request).create(
        actor, notebook_id,
        title=body.title,
        content=target["content"],
        source_message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Admin (L5) — central AI credentials, content reports
# ---------------------------------------------------------------------------


class CredentialCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    secret_value: str = Field(min_length=1, max_length=10_000)


class RotateRequest(BaseModel):
    new_secret: Optional[str] = Field(default=None, max_length=10_000)


class ReportCreate(BaseModel):
    target_type: str = Field(min_length=1, max_length=50)
    target_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)


admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@admin_router.post("/credentials", status_code=201)
async def set_credential(body: CredentialCreate, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_admin.set_credential(
        actor, provider=body.provider, name=body.name, secret_value=body.secret_value
    )


@admin_router.get("/credentials")
async def list_credentials(request: Request) -> list[dict[str, Any]]:
    actor = get_actor(request)
    return await request.app.state.guguta_admin.list_credentials(actor)


@admin_router.delete("/credentials/{credential_id}")
async def delete_credential(credential_id: uuid.UUID, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    await request.app.state.guguta_admin.delete_credential(actor, credential_id)
    return {"deleted": True}


@admin_router.post("/credentials/{credential_id}/rotate")
async def rotate_credential(
    credential_id: uuid.UUID, body: RotateRequest, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_admin.rotate_credential(
        actor, credential_id, new_secret=body.new_secret
    )


@admin_router.get("/reports")
async def list_reports(request: Request) -> list[dict[str, Any]]:
    actor = get_actor(request)
    return await request.app.state.guguta_admin.list_reports(actor)


reports_router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@reports_router.post("", status_code=201)
async def create_report(body: ReportCreate, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    try:
        target_uuid = uuid.UUID(body.target_id)
    except ValueError as exc:
        from open_notebook.exceptions import InvalidInputError

        raise InvalidInputError("target_id trebuie să fie UUID.") from exc
    return await request.app.state.guguta_admin.create_report(
        actor, target_type=body.target_type, target_id=target_uuid, reason=body.reason
    )


# ---------------------------------------------------------------------------
# Catalog (L6) — public browse + editor flows + instantiation
# ---------------------------------------------------------------------------


class TemplateCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    class_level: Optional[str] = Field(default=None, max_length=100)
    discipline: Optional[str] = Field(default=None, max_length=100)
    language: str = Field(default="ro", max_length=20)
    edition: Optional[str] = Field(default=None, max_length=100)
    rights_note: Optional[str] = Field(default=None, max_length=5000)


class VersionCreate(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)


admin_catalog_router = APIRouter(
    prefix="/api/v1/admin/catalog/templates", tags=["admin-catalog"]
)


@admin_catalog_router.post("", status_code=201)
async def admin_create_template(body: TemplateCreate, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_catalog.create_template(
        actor, **body.model_dump()
    )


@admin_catalog_router.post("/{template_id}/versions", status_code=201)
async def admin_create_version(
    template_id: uuid.UUID, body: VersionCreate, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_catalog.create_version(
        actor, template_id, items=body.items
    )


@admin_catalog_router.post("/{template_id}/versions/{version_id}/publish")
async def admin_publish_version(
    template_id: uuid.UUID, version_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_catalog.publish_version(
        actor, template_id, version_id
    )


@admin_catalog_router.post("/{template_id}/versions/{version_id}/retire")
async def admin_retire_version(
    template_id: uuid.UUID, version_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_catalog.retire_version(
        actor, template_id, version_id
    )


catalog_router = APIRouter(prefix="/api/v1/catalog/templates", tags=["catalog"])


@catalog_router.get("")
async def list_public_templates(request: Request) -> list[dict[str, Any]]:
    """A01: public catalog — visible to visitors (published only, no drafts)."""
    return await request.app.state.guguta_catalog.list_public_templates_visitor()


@catalog_router.get("/{template_id}")
async def get_public_template(
    template_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    # authenticated view adds nothing here; visitors and users see the same
    # published metadata (no drafts, no personal data leak either way)
    actor = get_actor(request)
    return await request.app.state.guguta_catalog.get_template(actor, template_id)


class InstantiateRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)


@catalog_router.post("/{template_id}/instances", status_code=201)
async def instantiate_template(
    template_id: uuid.UUID, body: InstantiateRequest, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_catalog.instantiate(
        actor, template_id, idempotency_key=body.idempotency_key
    )


# ---------------------------------------------------------------------------
# Sharing / import (L7)
# ---------------------------------------------------------------------------


class ShareCreate(BaseModel):
    source_ids: list[str] = Field(min_length=1)
    title: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)


class TokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)


class ImportRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=255)


shares_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/shares", tags=["shares"]
)


@shares_router.post("", status_code=201)
async def create_share(
    notebook_id: uuid.UUID, body: ShareCreate, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    try:
        source_uuids = [uuid.UUID(s) for s in body.source_ids]
    except ValueError as exc:
        from open_notebook.exceptions import InvalidInputError

        raise InvalidInputError("source_ids trebuie să fie UUID-uri.") from exc
    return await request.app.state.guguta_sharing.create_share(
        actor, notebook_id,
        source_ids=source_uuids, title=body.title, description=body.description,
    )


@shares_router.get("")
async def list_shares(notebook_id: uuid.UUID, request: Request) -> list[dict[str, Any]]:
    actor = get_actor(request)
    return await request.app.state.guguta_sharing.list_shares_for_notebook(
        actor, notebook_id
    )


@shares_router.post("/{share_id}/revoke")
async def revoke_share(
    notebook_id: uuid.UUID, share_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_sharing.revoke_share(
        actor, notebook_id, share_id
    )


imports_router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


@imports_router.post("/preview")
async def preview_import(body: TokenRequest, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_sharing.preview_import(
        actor, body.token
    )


@imports_router.post("", status_code=201)
async def import_snapshot(body: ImportRequest, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_sharing.import_snapshot(
        actor, body.token, idempotency_key=body.idempotency_key
    )
