"""Guguță API routers: /api/v1 — auth (sessions) and notebooks CRUD.

Routers stay thin; logic lives in services. Errors are typed domain
exceptions mapped by the app factory to contract status codes (GHID §5.1).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from typing import Any, Optional

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
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


class PasswordLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)


class PasswordRegisterRequest(PasswordLoginRequest):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    # Profil școlar și consimțăminte (migrarea 0024). Politica de
    # confidențialitate trebuie acceptată explicit; pentru clasele I–VIII
    # elevul confirmă că un părinte sau tutore știe și este de acord.
    school: str = Field(min_length=2, max_length=200)
    class_level: str = Field(min_length=1, max_length=20)
    privacy_accepted: bool = False
    parent_consent: bool = False


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    school: Optional[str] = Field(default=None, min_length=2, max_length=200)
    class_level: Optional[str] = Field(default=None, min_length=1, max_length=20)


class MeResponse(BaseModel):
    id: str
    display_name: str
    roles: list[str]
    # Funcții opționale ale instanței, ca interfața să afișeze doar ce e configurat.
    capabilities: dict[str, bool] = {}
    email: Optional[str] = None
    school: Optional[str] = None
    class_level: Optional[str] = None
    # kind -> versiunea acceptată ('privacy', 'terms', 'parent').
    consents: dict[str, str] = {}


# Versiunea politicii de confidențialitate și a termenilor afișate în interfață
# (frontend-guguta/app/confidentialitate, /termeni). La schimbare, interfața
# cere din nou acordul utilizatorilor cu o versiune mai veche.
PRIVACY_POLICY_VERSION = "2026-10-21"

CLASS_LEVELS: tuple[str, ...] = (
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"
)
# Clasele pentru care se cere confirmarea părintelui/tutorelui (decizia D-07
# din docs/guguta/DECIZII_EXTERNE.md rămâne deschisă; pragul este provizoriu).
PARENT_CONSENT_CLASSES: frozenset[str] = frozenset(CLASS_LEVELS[:8])


def _normalize_class_level(value: str) -> str:
    """Acceptă „V”, „5”, „a V-a”, „clasa a 5-a” și întoarce cifra romană canonică."""
    raw = value.strip().upper().replace("CLASA", "").replace("A ", " ").strip()
    raw = raw.strip(" .-").replace("-A", "").strip(" .-")
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= 12:
            return CLASS_LEVELS[index - 1]
    if raw in CLASS_LEVELS:
        return raw
    raise InvalidInputError("Clasa trebuie să fie între I și XII.")


def _normalize_school(value: str) -> str:
    school = " ".join(value.strip().split())
    if len(school) < 2:
        raise InvalidInputError("Școala este obligatorie.")
    return school[:200]


auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if (
        len(email) > 320
        or "@" not in email
        or email.startswith("@")
        or email.endswith("@")
    ):
        raise InvalidInputError("Adresa de email nu este validă.")
    local, _, domain = email.partition("@")
    if not local or "." not in domain or any(ch.isspace() for ch in email):
        raise InvalidInputError("Adresa de email nu este validă.")
    return email


def _normalize_name(value: str, label: str) -> str:
    name = " ".join(value.strip().split())
    if not name:
        raise InvalidInputError(f"{label} este obligatoriu.")
    return name[:120]


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        "pbkdf2_sha256"
        f"${iterations}"
        f"${base64.urlsafe_b64encode(salt).decode('ascii').rstrip('=')}"
        f"${base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')}"
    )


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw + "=" * (-len(salt_raw) % 4))
        expected = base64.urlsafe_b64decode(digest_raw + "=" * (-len(digest_raw) % 4))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _ensure_password_auth(request: Request) -> None:
    if request.app.state.guguta_config.auth_mode != "password":
        raise ActorDenied("Autentificarea cu email și parolă este dezactivată.")


async def _open_session_for_user(
    user_id: uuid.UUID, display_name: str, request: Request, response: Response
) -> MeResponse:
    sessions: SessionService = get_session_service(request)
    token, csrf = await sessions.create_session(user_id)
    set_session_cookie(response, request, token)
    response.headers[CSRF_HEADER] = csrf
    return MeResponse(id=str(user_id), display_name=display_name, roles=["user"])


@auth_router.post("/dev-login")
async def dev_login(
    body: DevLoginRequest, request: Request, response: Response
) -> MeResponse:
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


@auth_router.post("/register")
async def password_register(
    body: PasswordRegisterRequest, request: Request, response: Response
) -> MeResponse:
    _ensure_password_auth(request)
    email = _normalize_email(body.email)
    first_name = _normalize_name(body.first_name, "Prenumele")
    last_name = _normalize_name(body.last_name, "Numele")
    display_name = f"{first_name} {last_name}"
    school = _normalize_school(body.school)
    class_level = _normalize_class_level(body.class_level)
    if not body.privacy_accepted:
        raise InvalidInputError(
            "Contul se poate crea doar după acceptarea politicii de confidențialitate."
        )
    if class_level in PARENT_CONSENT_CLASSES and not body.parent_consent:
        raise InvalidInputError(
            "Pentru clasele I–VIII este nevoie de confirmarea unui părinte sau tutore."
        )
    password_hash = _hash_password(body.password)
    engine = request.app.state.guguta_engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        existing = (
            await conn.execute(
                text("SELECT 1 FROM password_credentials WHERE email = :email"),
                {"email": email},
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise InvalidInputError("Există deja un cont cu acest email.")
        user_id = (
            await conn.execute(
                text("SELECT guguta_provision_user(:issuer, :subject, :name, :email)"),
                {
                    "issuer": "password",
                    "subject": email,
                    "name": display_name,
                    "email": email,
                },
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO password_credentials (user_id, email, password_hash) "
                "VALUES (:user_id, :email, :password_hash)"
            ),
            {"user_id": user_id, "email": email, "password_hash": password_hash},
        )
    from open_notebook.database.guguta.engine import actor_connection

    async with actor_connection(engine, user_id) as conn:
        await conn.execute(
            text("UPDATE users SET school=:school, class_level=:class_level WHERE id=:id"),
            {"school": school, "class_level": class_level, "id": user_id},
        )
        consents = [("privacy", PRIVACY_POLICY_VERSION), ("terms", PRIVACY_POLICY_VERSION)]
        if body.parent_consent:
            consents.append(("parent", PRIVACY_POLICY_VERSION))
        for kind, version in consents:
            await conn.execute(
                text(
                    "INSERT INTO user_consents (user_id, kind, version) VALUES (:u, :k, :v) "
                    "ON CONFLICT (user_id, kind) DO UPDATE SET version=EXCLUDED.version, accepted_at=now()"
                ),
                {"u": user_id, "k": kind, "v": version},
            )
    return await _open_session_for_user(user_id, display_name, request, response)


@auth_router.post("/login")
async def password_login(
    body: PasswordLoginRequest, request: Request, response: Response
) -> MeResponse:
    _ensure_password_auth(request)
    email = _normalize_email(body.email)
    engine = request.app.state.guguta_engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT user_id, password_hash, display_name, roles FROM guguta_password_auth_lookup(:email)"
                    ),
                    {"email": email},
                )
            )
            .mappings()
            .first()
        )
    if row is None or not _verify_password(body.password, str(row["password_hash"])):
        raise AuthenticationError("Email sau parolă incorectă.")
    return await _open_session_for_user(
        row["user_id"], str(row["display_name"]), request, response
    )


_STATE_COOKIE = "guguta_oidc_state"


def _safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/app"
    if "\r" in value or "\n" in value:
        return "/app"
    return value


@auth_router.get("/oidc/login", status_code=307)
async def oidc_login(
    request: Request, response: Response, next_path: str = Query("/app", alias="next")
):
    """Start the OIDC Authorization Code + PKCE flow (ADR-0003).

    Only available when auth_mode=oidc and an OIDC client is configured on
    app.state (production path); dev-login remains the test-mode path.
    The state cookie is set ON THE RETURNED redirect object (F01).
    """
    config = request.app.state.guguta_config
    if config.auth_mode != "oidc":
        raise ActorDenied("OIDC nu este activat.")
    client = request.app.state.guguta_oidc
    url, cookie_value = await client.begin_login(
        request.app.state.guguta_state_codec, return_to=_safe_return_to(next_path)
    )
    redirect = RedirectResponse(url, status_code=307)
    redirect.set_cookie(
        _STATE_COOKIE,
        cookie_value,
        httponly=True,
        samesite="lax",
        secure=config.public_origin.startswith("https://"),
        max_age=600,
        path="/",
    )
    return redirect


@auth_router.get("/oidc/callback")
async def oidc_callback(
    request: Request, response: Response, code: str = "", state: str = ""
) -> RedirectResponse:
    """Finish the OIDC flow: validate, provision, open the session.
    Session cookie + CSRF are set ON THE RETURNED redirect object (F01)."""
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
                {
                    "i": result.issuer,
                    "s": result.subject,
                    "n": result.display_name,
                    "e": result.email,
                },
            )
        ).scalar_one()
    sessions: SessionService = get_session_service(request)
    token, csrf = await sessions.create_session(user_id)
    redirect = RedirectResponse(_safe_return_to(result.return_to), status_code=303)
    redirect.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=config.public_origin.startswith("https://"),
        path="/",
    )
    redirect.headers[CSRF_HEADER] = csrf
    redirect.delete_cookie(_STATE_COOKIE, path="/")
    return redirect


@auth_router.get("/config")
async def auth_config(request: Request) -> dict[str, str]:
    """Public auth-mode discovery for the login screen (B15): reads from
    the validated app.state config, never from a fresh env re-read."""
    try:
        config = request.app.state.guguta_config
        mode = config.auth_mode
    except AttributeError:
        mode = "oidc"
    return {"auth_mode": mode, "privacy_version": PRIVACY_POLICY_VERSION}


@auth_router.get("/csrf")
async def csrf_bootstrap(request: Request) -> dict[str, str]:
    """F02: safe CSRF bootstrap for an existing session — the session cookie
    authenticates, the returned token is bound to it server-side."""
    actor = get_actor(request)
    sessions: SessionService = get_session_service(request)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthenticationError("Autentificare necesară.")
    return {"csrf": sessions.csrf_token_for(token), "actor_id": str(actor.actor_id)}


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
    return await _me_response(request, actor)


async def _me_response(request: Request, actor: ActorContext) -> MeResponse:
    config = request.app.state.guguta_config
    from sqlalchemy import text

    from open_notebook.database.guguta.engine import actor_connection

    async with actor_connection(request.app.state.guguta_engine, actor.actor_id) as conn:
        row = (
            (
                await conn.execute(
                    text("SELECT display_name, email, school, class_level FROM users WHERE id=:id"),
                    {"id": actor.actor_id},
                )
            )
            .mappings()
            .first()
        )
        consents = (
            await conn.execute(
                text("SELECT kind, version FROM user_consents WHERE user_id=:id"),
                {"id": actor.actor_id},
            )
        ).all()
    return MeResponse(
        id=str(actor.actor_id),
        display_name=str(row["display_name"]) if row else actor.display_name,
        roles=sorted(actor.roles),
        capabilities={"playquiz": bool(config.playquiz_enabled)},
        email=row["email"] if row else None,
        school=row["school"] if row else None,
        class_level=row["class_level"] if row else None,
        consents={str(kind): str(version) for kind, version in consents},
    )


@auth_router.patch("/me")
async def update_me(body: ProfileUpdateRequest, request: Request) -> MeResponse:
    """Profilul propriu: nume afișat, școală, clasă (dreptul la rectificare)."""
    actor = get_actor(request)
    updates: dict[str, Any] = {}
    if body.display_name is not None:
        updates["display_name"] = _normalize_name(body.display_name, "Numele")[:255]
    if body.school is not None:
        updates["school"] = _normalize_school(body.school)
    if body.class_level is not None:
        updates["class_level"] = _normalize_class_level(body.class_level)
    if not updates:
        raise InvalidInputError("Nimic de actualizat.")
    from sqlalchemy import text

    from open_notebook.database.guguta.engine import actor_connection

    assignments = ", ".join(f"{column}=:{column}" for column in updates)
    async with actor_connection(request.app.state.guguta_engine, actor.actor_id) as conn:
        await conn.execute(
            text(f"UPDATE users SET {assignments} WHERE id=:id"),
            {**updates, "id": actor.actor_id},
        )
    return await _me_response(request, actor)


@auth_router.delete("/me")
async def delete_me(request: Request, response: Response) -> dict[str, bool]:
    """Dreptul la ștergere: carnetele proprii se șterg (cu fișierele lor, prin
    mecanismele existente de ștergere), identitățile, credențialele, sesiunile
    și consimțămintele dispar, iar contul rămâne doar ca rând anonimizat cu
    status 'deleted' (referințele RESTRICT din audit/catalog/partajări)."""
    actor = get_actor(request)
    from sqlalchemy import text

    from open_notebook.database.guguta.engine import actor_connection

    engine = request.app.state.guguta_engine
    async with actor_connection(engine, actor.actor_id) as conn:
        await conn.execute(
            text("DELETE FROM digital_notebooks WHERE owner_id=:id"), {"id": actor.actor_id}
        )
        for table in ("user_consents", "password_credentials", "identities", "sessions"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE user_id=:id"), {"id": actor.actor_id}
            )
        await conn.execute(
            text(
                "UPDATE users SET display_name='Cont șters', email=NULL, school=NULL, "
                "class_level=NULL, status='deleted' WHERE id=:id"
            ),
            {"id": actor.actor_id},
        )
    clear_session_cookie(response, request)
    return {"ok": True}


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
    # Fixare „sus" în lista proprietarului: true fixează, false anulează.
    pinned: Optional[bool] = None


notebooks_router = APIRouter(prefix="/api/v1/notebooks", tags=["notebooks"])


@notebooks_router.post("", status_code=201)
async def create_notebook(body: NotebookCreate, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    return await service.create(actor, title=body.title, description=body.description)


@notebooks_router.get("")
async def list_notebooks(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    sort: str = "created_desc",
    status: Optional[str] = None,
) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    if sort not in (
        "created_desc",
        "created_asc",
        "title_asc",
        "title_desc",
        "updated_desc",
    ):
        raise InvalidInputError("Sortare neacceptată.")
    if status not in (None, "active", "archived"):
        raise InvalidInputError("Stare neacceptată.")
    return await service.list_for_actor(
        actor,
        page=page,
        page_size=page_size,
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
    notebook_id: uuid.UUID,
    body: NotebookUpdate,
    request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    service = request.app.state.guguta_notebooks
    return await service.update(
        actor,
        notebook_id,
        title=body.title,
        description=body.description,
        archive=body.archive,
        pinned=body.pinned,
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



class TextSourceCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    text: str = Field(min_length=1, max_length=2_000_000)


def get_sources_service(request: Request) -> Any:
    return request.app.state.guguta_sources


sources_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/sources", tags=["sources"]
)


# ---------------------------------------------------------------------------
# Speech to text (Romanian Parakeet)
# ---------------------------------------------------------------------------

speech_router = APIRouter(prefix="/api/v1/speech", tags=["speech"])


@speech_router.post("/transcriptions")
async def transcribe_speech(request: Request, file: UploadFile) -> dict[str, str]:
    get_actor(request)
    return await request.app.state.guguta_speech.transcribe(
        stream=file.file,
        filename=file.filename,
        content_type=file.content_type,
    )


@sources_router.post("/file", status_code=201)
async def upload_source(
    notebook_id: uuid.UUID, request: Request, file: UploadFile
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    return await service.upload_file(
        actor,
        notebook_id,
        stream=file.file,
        original_name=file.filename,
        local_name=None,
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
async def list_sources(
    notebook_id: uuid.UUID, request: Request
) -> list[dict[str, Any]]:
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
    notebook_id: uuid.UUID,
    source_id: uuid.UUID,
    body: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    service = get_sources_service(request)
    if not set(body.keys()) <= {"local_name", "selected_for_chat"}:
        from open_notebook.exceptions import InvalidInputError

        raise InvalidInputError("Câmpuri neacceptate.")
    return await service.update(
        actor,
        notebook_id,
        source_id,
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
    from urllib.parse import quote

    from fastapi.responses import Response

    actor = get_actor(request)
    service = get_sources_service(request)
    data, mime, original = await service.download(actor, notebook_id, source_id)
    # F24: safe Content-Disposition with ASCII fallback + UTF-8 extension
    safe_name = (
        (original or "material").replace('"', "").replace("\r", "").replace("\n", "")
    )
    ascii_name = safe_name.encode("ascii", "replace").decode("ascii")
    utf8_name = quote(safe_name)
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
        )
    }
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
        actor.actor_id,
        notebook_id,
        body.query,
        mode=body.mode,
        limit=body.limit,
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
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)


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
async def list_sessions(
    notebook_id: uuid.UUID, request: Request
) -> list[dict[str, Any]]:
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


@chat_router.get("/{session_id}/attachments")
async def list_chat_attachments(notebook_id: uuid.UUID, session_id: uuid.UUID, request: Request):
    return await request.app.state.guguta_attachments.list(get_actor(request), notebook_id, session_id)


@chat_router.post("/{session_id}/attachments", status_code=201)
async def upload_chat_attachments(notebook_id: uuid.UUID, session_id: uuid.UUID,
                                  request: Request, files: list[UploadFile] = File(...)):
    return await request.app.state.guguta_attachments.upload(get_actor(request), notebook_id, session_id, files)


@chat_router.delete("/{session_id}/attachments/{source_id}")
async def remove_chat_attachment(notebook_id: uuid.UUID, session_id: uuid.UUID,
                                 source_id: uuid.UUID, request: Request):
    return {"deleted": await request.app.state.guguta_attachments.remove(
        get_actor(request), notebook_id, session_id, source_id)}


@chat_router.get("/{session_id}/attachments/{source_id}/download")
async def download_chat_attachment(notebook_id: uuid.UUID, session_id: uuid.UUID,
                                   source_id: uuid.UUID, request: Request):
    await request.app.state.guguta_attachments.check_file(get_actor(request), notebook_id, session_id, source_id)
    return await download_source(notebook_id, source_id, request)


@chat_router.delete("/{session_id}")
async def delete_chat_session(notebook_id: uuid.UUID, session_id: uuid.UUID, request: Request):
    deleted = await request.app.state.guguta_attachments.delete_chat(get_actor(request), notebook_id, session_id)
    evidence = request.app.state.guguta_chat._pdf_evidence
    if evidence is not None:
        evidence._cache.clear()
        evidence._size = 0
    return {"deleted": deleted}


@chat_router.post("/{session_id}/messages")
async def send_message(
    notebook_id: uuid.UUID,
    session_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    await request.app.state.guguta_attachments.validate(actor, notebook_id, session_id, body.attachment_ids)
    service = request.app.state.guguta_chat.for_session(session_id, body.attachment_ids)
    return await service.send_message(
        actor,
        notebook_id,
        session_id,
        content=body.content,
        idempotency_key=body.idempotency_key,
    )


@chat_router.post("/{session_id}/messages/stream")
async def send_message_stream(
    notebook_id: uuid.UUID,
    session_id: uuid.UUID,
    body: MessageCreate,
    request: Request,
) -> Any:
    """SSE endpoint: streams chat response token by token."""

    from fastapi.responses import StreamingResponse

    actor = get_actor(request)
    await request.app.state.guguta_attachments.validate(actor, notebook_id, session_id, body.attachment_ids)
    service = request.app.state.guguta_chat.for_session(session_id, body.attachment_ids)
    gen = await service.send_message_stream(
        actor,
        notebook_id,
        session_id,
        content=body.content,
        idempotency_key=body.idempotency_key,
    )

    async def _sse(gen):
        # serviciul yield-uiește deja linii JSON complete — fără re-dump
        async for event in gen:
            yield f"data: {event}\n\n"

    return StreamingResponse(
        _sse(gen),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@chat_router.get("/{session_id}/messages/{message_id}/citations")
async def get_citations(
    notebook_id: uuid.UUID,
    session_id: uuid.UUID,
    message_id: uuid.UUID,
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


notes_router = APIRouter(prefix="/api/v1/notebooks/{notebook_id}/notes", tags=["notes"])


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
    notebook_id: uuid.UUID,
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    body: SaveAnswerRequest,
    request: Request,
) -> dict[str, Any]:
    actor = get_actor(request)
    chat = request.app.state.guguta_chat
    messages = await chat.list_messages(actor, notebook_id, session_id)
    target = next((m for m in messages if m["id"] == message_id), None)
    if target is None:
        from api.services.guguta.chat import ChatSessionNotFound

        raise ChatSessionNotFound()
    return await get_notes_service(request).create(
        actor,
        notebook_id,
        title=body.title,
        content=target["content"],
        source_message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Audio Overview — single-speaker Brief / Deep Dive
# ---------------------------------------------------------------------------


class AudioOverviewCreate(BaseModel):
    format: str = Field(pattern="^(brief|deep_dive)$")
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=30)
    instructions: str | None = Field(default=None, max_length=4000)


audio_overviews_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/audio-overviews",
    tags=["audio-overviews"],
)


def get_audio_overviews_service(request: Request) -> Any:
    return request.app.state.guguta_audio_overviews


def _parse_audio_byte_range(value: str, total_size: int) -> tuple[int, int]:
    """Parse one RFC 7233 byte range and return its inclusive bounds.

    Browsers issue a single range while seeking in an HTML audio element. We
    intentionally reject multipart ranges because the player does not need
    them and a multipart response would require a different response body.
    """

    unit, separator, raw_range = value.partition("=")
    if separator != "=" or unit.strip().lower() != "bytes":
        raise ValueError("unsupported range unit")
    if total_size <= 0 or "," in raw_range:
        raise ValueError("range is not satisfiable")

    start_raw, dash, end_raw = raw_range.strip().partition("-")
    if dash != "-":
        raise ValueError("invalid range")
    start_raw = start_raw.strip()
    end_raw = end_raw.strip()

    if start_raw:
        if not start_raw.isdigit() or (end_raw and not end_raw.isdigit()):
            raise ValueError("invalid range bounds")
        start = int(start_raw)
        if start >= total_size:
            raise ValueError("range starts beyond the resource")
        end = int(end_raw) if end_raw else total_size - 1
        if end < start:
            raise ValueError("range ends before it starts")
        return start, min(end, total_size - 1)

    if not end_raw.isdigit():
        raise ValueError("invalid suffix range")
    suffix_size = int(end_raw)
    if suffix_size <= 0:
        raise ValueError("empty suffix range")
    return max(total_size - suffix_size, 0), total_size - 1


def _audio_download_response(
    data: bytes,
    mime: str,
    filename: str,
    range_header: str | None,
) -> Response:
    """Return a complete or partial audio response suitable for seeking."""

    from urllib.parse import quote

    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
    ascii_name = safe_name.encode("ascii", "replace").decode("ascii")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": (
            f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(safe_name)}"
        ),
    }
    if range_header is None:
        return Response(content=data, media_type=mime, headers=headers)

    try:
        start, end = _parse_audio_byte_range(range_header, len(data))
    except ValueError:
        headers["Content-Range"] = f"bytes */{len(data)}"
        return Response(status_code=416, headers=headers)

    headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
    return Response(
        content=data[start : end + 1],
        status_code=206,
        media_type=mime,
        headers=headers,
    )


@audio_overviews_router.post("", status_code=202)
async def create_audio_overview(
    notebook_id: uuid.UUID, body: AudioOverviewCreate, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await get_audio_overviews_service(request).create(
        actor,
        notebook_id,
        format_name=body.format,
        source_ids=body.source_ids,
        instructions=body.instructions,
    )


@audio_overviews_router.get("")
async def list_audio_overviews(
    notebook_id: uuid.UUID, request: Request
) -> list[dict[str, Any]]:
    actor = get_actor(request)
    return await get_audio_overviews_service(request).list_for_notebook(
        actor, notebook_id
    )


@audio_overviews_router.get("/{overview_id}")
async def get_audio_overview(
    notebook_id: uuid.UUID, overview_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    actor = get_actor(request)
    return await get_audio_overviews_service(request).get(
        actor, notebook_id, overview_id
    )


@audio_overviews_router.get("/{overview_id}/audio")
async def download_audio_overview(
    notebook_id: uuid.UUID, overview_id: uuid.UUID, request: Request
) -> Response:
    actor = get_actor(request)
    data, mime, filename = await get_audio_overviews_service(request).download(
        actor, notebook_id, overview_id
    )
    return _audio_download_response(
        data,
        mime,
        filename,
        request.headers.get("range"),
    )


@audio_overviews_router.post("/{overview_id}/retry")
async def retry_audio_overview(
    notebook_id: uuid.UUID, overview_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    actor = get_actor(request)
    return {
        "requeued": await get_audio_overviews_service(request).retry(
            actor, notebook_id, overview_id
        )
    }


@audio_overviews_router.delete("/{overview_id}")
async def delete_audio_overview(
    notebook_id: uuid.UUID, overview_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    actor = get_actor(request)
    return {
        "deleted": await get_audio_overviews_service(request).delete(
            actor, notebook_id, overview_id
        )
    }


# ---------------------------------------------------------------------------
# Flashcards — source-grounded decks and persistent study sessions
# ---------------------------------------------------------------------------


class FlashcardDeckCreate(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=30)
    quantity: str = Field(default="standard", pattern="^(fewer|standard|more)$")
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    instructions: str | None = Field(default=None, max_length=4000)


class FlashcardSessionCreate(BaseModel):
    mode: str = Field(default="all", pattern="^(all|same|missed)$")


class FlashcardSessionUpdate(BaseModel):
    current_index: int = Field(ge=0)
    results: dict[str, str] = Field(default_factory=dict)
    card_order: list[str] | None = None
    completed: bool = False


flashcards_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/flashcard-decks", tags=["flashcards"]
)


def get_flashcard_service(request: Request) -> Any:
    return request.app.state.guguta_flashcards


@flashcards_router.post("", status_code=202)
async def create_flashcard_deck(
    notebook_id: uuid.UUID, body: FlashcardDeckCreate, request: Request
) -> dict[str, Any]:
    return await get_flashcard_service(request).create(
        get_actor(request),
        notebook_id,
        source_ids=body.source_ids,
        quantity=body.quantity,
        difficulty=body.difficulty,
        instructions=body.instructions,
    )


@flashcards_router.get("")
async def list_flashcard_decks(
    notebook_id: uuid.UUID, request: Request
) -> list[dict[str, Any]]:
    return await get_flashcard_service(request).list_for_notebook(
        get_actor(request), notebook_id
    )


@flashcards_router.get("/{deck_id}")
async def get_flashcard_deck(
    notebook_id: uuid.UUID, deck_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    return await get_flashcard_service(request).get(
        get_actor(request), notebook_id, deck_id
    )


@flashcards_router.delete("/{deck_id}")
async def delete_flashcard_deck(
    notebook_id: uuid.UUID, deck_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    return {
        "deleted": await get_flashcard_service(request).delete(
            get_actor(request), notebook_id, deck_id
        )
    }


@flashcards_router.post("/{deck_id}/retry")
async def retry_flashcard_deck(
    notebook_id: uuid.UUID, deck_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    return {
        "requeued": await get_flashcard_service(request).retry(
            get_actor(request), notebook_id, deck_id
        )
    }


@flashcards_router.delete("/{deck_id}/cards/{card_id}")
async def delete_flashcard(
    notebook_id: uuid.UUID, deck_id: uuid.UUID, card_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    return {
        "deleted": await get_flashcard_service(request).delete_card(
            get_actor(request), notebook_id, deck_id, card_id
        )
    }


@flashcards_router.post("/{deck_id}/cards/{card_id}/explain")
async def explain_flashcard(
    notebook_id: uuid.UUID, deck_id: uuid.UUID, card_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    return await get_flashcard_service(request).explain(
        get_actor(request), notebook_id, deck_id, card_id
    )


@flashcards_router.post("/{deck_id}/sessions", status_code=201)
async def create_flashcard_session(
    notebook_id: uuid.UUID,
    deck_id: uuid.UUID,
    body: FlashcardSessionCreate,
    request: Request,
) -> dict[str, Any]:
    return await get_flashcard_service(request).create_session(
        get_actor(request), notebook_id, deck_id, mode=body.mode
    )


@flashcards_router.patch("/{deck_id}/sessions/{session_id}")
async def update_flashcard_session(
    notebook_id: uuid.UUID,
    deck_id: uuid.UUID,
    session_id: uuid.UUID,
    body: FlashcardSessionUpdate,
    request: Request,
) -> dict[str, Any]:
    return await get_flashcard_service(request).update_session(
        get_actor(request),
        notebook_id,
        deck_id,
        session_id,
        current_index=body.current_index,
        results=body.results,
        card_order=body.card_order,
        completed=body.completed,
    )


@flashcards_router.get("/{deck_id}/export.csv")
async def export_flashcard_deck(
    notebook_id: uuid.UUID, deck_id: uuid.UUID, request: Request
) -> Response:
    from urllib.parse import quote

    data, filename = await get_flashcard_service(request).csv_export(
        get_actor(request), notebook_id, deck_id
    )
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"flashcards.csv\"; filename*=UTF-8''{quote(safe_name)}"
        },
    )


# ---------------------------------------------------------------------------
# Quiz — grounded questions, server-side grading and persistent attempts
# ---------------------------------------------------------------------------


class QuizCreate(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=30)
    quantity: str = Field(default="standard", pattern="^(fewer|standard|more)$")
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    question_types: list[str] = Field(min_length=1, max_length=4)
    instructions: str | None = Field(default=None, max_length=4000)


class QuizAnswer(BaseModel):
    question_id: uuid.UUID
    response: str | list[str]
    hint_used: bool = False


class QuizExplain(BaseModel):
    response: str | list[str] | None = None


class QuizOptionInput(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1, max_length=2000)
    is_correct: bool
    rationale: str = Field(min_length=1, max_length=4000)


class QuizQuestionInput(BaseModel):
    question_type: str = Field(
        pattern="^(multiple_choice|multiple_select|fill_in_blank|short_answer)$"
    )
    prompt: str = Field(min_length=1, max_length=4000)
    hint: str = Field(default="", max_length=2000)
    concepts: list[str] = Field(default_factory=list, max_length=20)
    options: list[QuizOptionInput] = Field(default_factory=list, max_length=10)
    accepted_answers: list[str] = Field(default_factory=list, max_length=20)
    reference_answer: str = Field(default="", max_length=8000)
    required_concepts: list[str] = Field(default_factory=list, max_length=20)
    optional_concepts: list[str] = Field(default_factory=list, max_length=20)


quizzes_router = APIRouter(
    prefix="/api/v1/notebooks/{notebook_id}/quizzes", tags=["quizzes"]
)


def get_quiz_service(request: Request) -> Any:
    return request.app.state.guguta_quizzes


@quizzes_router.post("", status_code=202)
async def create_quiz(
    notebook_id: uuid.UUID, body: QuizCreate, request: Request
) -> dict[str, Any]:
    return await get_quiz_service(request).create(
        get_actor(request),
        notebook_id,
        source_ids=body.source_ids,
        quantity=body.quantity,
        difficulty=body.difficulty,
        question_types=body.question_types,
        instructions=body.instructions,
    )


@quizzes_router.get("")
async def list_quizzes(
    notebook_id: uuid.UUID, request: Request
) -> list[dict[str, Any]]:
    return await get_quiz_service(request).list(get_actor(request), notebook_id)


@quizzes_router.get("/{quiz_id}")
async def get_quiz(
    notebook_id: uuid.UUID, quiz_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    return await get_quiz_service(request).get(get_actor(request), notebook_id, quiz_id)


@quizzes_router.delete("/{quiz_id}")
async def delete_quiz(
    notebook_id: uuid.UUID, quiz_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    return {
        "deleted": await get_quiz_service(request).delete(
            get_actor(request), notebook_id, quiz_id
        )
    }


@quizzes_router.post("/{quiz_id}/retry")
async def retry_quiz(
    notebook_id: uuid.UUID, quiz_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    return {
        "requeued": await get_quiz_service(request).retry(
            get_actor(request), notebook_id, quiz_id
        )
    }


@quizzes_router.post("/{quiz_id}/attempts", status_code=201)
async def create_quiz_attempt(
    notebook_id: uuid.UUID, quiz_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    return await get_quiz_service(request).create_attempt(
        get_actor(request), notebook_id, quiz_id
    )


@quizzes_router.post("/{quiz_id}/attempts/{attempt_id}/answers")
async def answer_quiz(
    notebook_id: uuid.UUID,
    quiz_id: uuid.UUID,
    attempt_id: uuid.UUID,
    body: QuizAnswer,
    request: Request,
) -> dict[str, Any]:
    return await get_quiz_service(request).answer(
        get_actor(request),
        notebook_id,
        quiz_id,
        attempt_id,
        question_id=body.question_id,
        response=body.response,
        hint_used=body.hint_used,
    )


@quizzes_router.get("/{quiz_id}/attempts/{attempt_id}/results")
async def quiz_results(
    notebook_id: uuid.UUID, quiz_id: uuid.UUID, attempt_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    return await get_quiz_service(request).results(
        get_actor(request), notebook_id, quiz_id, attempt_id
    )


class PlayQuizExportRequest(BaseModel):
    # Acordul explicit pentru transmiterea numelui și a e-mailului (ADR-023);
    # se cere o singură dată per utilizator.
    consent: bool = False


def get_playquiz_export_service(request: Request) -> Any:
    return request.app.state.guguta_playquiz_export


@quizzes_router.get("/{quiz_id}/playquiz")
async def playquiz_export_status(
    notebook_id: uuid.UUID, quiz_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    return await get_playquiz_export_service(request).status(
        get_actor(request), notebook_id, quiz_id
    )


@quizzes_router.post("/{quiz_id}/playquiz")
async def playquiz_export(
    notebook_id: uuid.UUID,
    quiz_id: uuid.UUID,
    body: PlayQuizExportRequest,
    request: Request,
) -> dict[str, Any]:
    return await get_playquiz_export_service(request).export(
        get_actor(request), notebook_id, quiz_id, consent=body.consent
    )


@quizzes_router.post("/{quiz_id}/questions/{question_id}/explain")
async def explain_quiz_question(
    notebook_id: uuid.UUID,
    quiz_id: uuid.UUID,
    question_id: uuid.UUID,
    body: QuizExplain,
    request: Request,
) -> dict[str, Any]:
    return await get_quiz_service(request).explain(
        get_actor(request), notebook_id, quiz_id, question_id, body.response
    )


@quizzes_router.post("/{quiz_id}/questions", status_code=201)
async def add_quiz_question(
    notebook_id: uuid.UUID,
    quiz_id: uuid.UUID,
    body: QuizQuestionInput,
    request: Request,
) -> dict[str, Any]:
    return await get_quiz_service(request).add_question(
        get_actor(request), notebook_id, quiz_id, data=body.model_dump()
    )


@quizzes_router.put("/{quiz_id}/questions/{question_id}")
async def update_quiz_question(
    notebook_id: uuid.UUID,
    quiz_id: uuid.UUID,
    question_id: uuid.UUID,
    body: QuizQuestionInput,
    request: Request,
) -> dict[str, Any]:
    return await get_quiz_service(request).update_question(
        get_actor(request), notebook_id, quiz_id, question_id, data=body.model_dump()
    )


@quizzes_router.delete("/{quiz_id}/questions/{question_id}")
async def delete_quiz_question(
    notebook_id: uuid.UUID, quiz_id: uuid.UUID, question_id: uuid.UUID, request: Request
) -> dict[str, bool]:
    return {
        "deleted": await get_quiz_service(request).delete_question(
            get_actor(request), notebook_id, quiz_id, question_id
        )
    }


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
async def delete_credential(
    credential_id: uuid.UUID, request: Request
) -> dict[str, Any]:
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


class VersionItem(BaseModel):
    material_version_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=500)


class VersionCreate(BaseModel):
    items: list[VersionItem] = Field(min_length=1)


admin_catalog_router = APIRouter(
    prefix="/api/v1/admin/catalog/templates", tags=["admin-catalog"]
)


@admin_catalog_router.post("", status_code=201)
async def admin_create_template(
    body: TemplateCreate, request: Request
) -> dict[str, Any]:
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
    expires_in_days: int | None = Field(default=30)


class TokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=2048)


class ImportRequest(BaseModel):
    token: str = Field(min_length=1, max_length=2048)
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
        actor,
        notebook_id,
        source_ids=source_uuids,
        title=body.title,
        description=body.description,
        expires_in_days=body.expires_in_days,
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
    return await request.app.state.guguta_sharing.preview_import(actor, body.token)


@imports_router.post("", status_code=201)
async def import_snapshot(body: ImportRequest, request: Request) -> dict[str, Any]:
    actor = get_actor(request)
    return await request.app.state.guguta_sharing.import_snapshot(
        actor, body.token, idempotency_key=body.idempotency_key
    )
