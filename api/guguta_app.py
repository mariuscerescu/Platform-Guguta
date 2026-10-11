"""Guguță API application factory.

Standalone FastAPI app for the Guguță surface (`api.guguta_app:app`):
- only /api/v1 routes + health — upstream routers are not mounted (R26:
  unported upstream endpoints cannot be reached, not merely hidden);
- session-cookie middleware resolving the ActorContext for every request;
- CSRF/Origin verification for cookie-based mutations (login routes are
  exempt from CSRF — no session exists yet; Origin checks still apply);
- typed domain exceptions mapped to contract status codes;
- health/readiness separated (R72 groundwork; AI status lands with providers).

User provisioning (first login) runs through `guguta_provision_user`
(SECURITY DEFINER, migration 0002) because no actor context exists yet and
RLS correctly denies anonymous INSERTs.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.routers.guguta_v1 import (
    admin_catalog_router,
    admin_router,
    audio_overviews_router,
    auth_router,
    catalog_router,
    chat_router,
    flashcards_router,
    imports_router,
    jobs_router,
    notebooks_router,
    notes_router,
    quizzes_router,
    reports_router,
    search_router,
    shares_router,
    sources_router,
    speech_router,
)
from api.routers.guguta_voice import voice_router
from api.services.guguta.voice import VoiceRateLimited, VoiceService, VoiceUnavailable
from api.services.guguta.admin import AdminService
from api.services.guguta.audio_overviews import AudioOverviewService
from api.services.guguta.catalog import (
    CatalogService,
    CatalogValidation,
    RetiredTemplate,
    TemplateNotFound,
)
from api.services.guguta.chat import (
    ChatProviderUnavailable,
    ChatService,
    ChatSessionNotFound,
    ChatValidation,
    IdempotencyConflict,
    SourcesRequired,
)
from api.services.guguta.flashcards import FlashcardService
from api.services.guguta.notebooks import (
    NotebookNotFound,
    NotebookService,
    NotebookValidation,
)
from api.services.guguta.notes import (
    NoteNotFound,
    NotesService,
    NoteValidation,
)
from api.services.guguta.quizzes import QuizService
from api.services.guguta.search import SearchService
from api.services.guguta.sharing import (
    QuotaExceeded as ShareQuotaExceeded,
)
from api.services.guguta.sharing import (
    ShareExpired,
    ShareNotFound,
    ShareRevoked,
    ShareValidation,
    SharingService,
)
from api.services.guguta.sources import (
    QuotaExceeded,
    SourceNotFound,
    SourcesService,
    SourceValidation,
)
from api.services.guguta.speech import (
    SpeechService,
    SpeechUnavailable,
    SpeechValidation,
)
from open_notebook.auth.guguta.actor import ActorDenied
from open_notebook.auth.guguta.oidc import OidcError, SignedStateCodec
from open_notebook.auth.guguta.sessions import (
    CSRF_HEADER,
    SESSION_COOKIE,
    SessionService,
)
from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import create_engine_for_role
from open_notebook.exceptions import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenNotebookError,
)

_CSRF_EXEMPT_PREFIXES = ("/api/v1/auth/",)


def _error(code: str, message: str, status: int, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "request_id": request_id},
    )


def create_guguta_app(config: GugutaConfig) -> FastAPI:
    app = FastAPI(
        title="Platforma Guguță API",
        version="0.1.0",
        docs_url=None,  # no public swagger on the Guguță surface (R65)
        redoc_url=None,
        openapi_url=None,
    )
    app.state.guguta_config = config
    # Runtime role engine built eagerly so tests and health probes can use it;
    # disposed on shutdown.
    engine = create_engine_for_role(config, "api")
    app.state.guguta_engine = engine
    app.state.guguta_sessions = SessionService(
        engine,
        server_secret=config.server_secret,
        absolute_ttl=timedelta(hours=config.session_absolute_ttl_hours),
        inactivity_ttl=timedelta(minutes=config.session_inactivity_ttl_minutes),
    )
    app.state.guguta_notebooks = NotebookService(engine)
    from open_notebook.ai.guguta.chat import get_chat_provider
    from open_notebook.jobs.guguta.embeddings import (
        get_provider as get_embedding_provider,
    )
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    embedding_provider = get_embedding_provider(
        config.embedding_provider, config.embedding_dimension, config
    )
    app.state.guguta_sources = SourcesService(
        engine,
        FilesystemStorage(config.storage_root),
        max_upload_mib=config.max_upload_mib,
        max_pdf_pages=config.max_pdf_pages,
        max_sources_per_notebook=config.max_sources_per_notebook,
        quota_mib_per_user=config.quota_mib_per_user,
        max_image_pixels=config.max_image_pixels,
        max_image_dimension=config.max_image_dimension,
        attachment_max_mib=config.chat_attachment_max_mib,
        attachment_total_mib=config.chat_attachment_total_mib,
        attachment_max_per_message=config.chat_attachment_max_per_message,
        attachment_max_per_session=config.chat_attachment_max_per_session,
    )
    from api.services.guguta.chat_attachments import ChatAttachmentsService

    app.state.guguta_attachments = ChatAttachmentsService(app.state.guguta_sources)
    if config.rerank_provider == "openrouter":
        from open_notebook.ai.guguta.openrouter import OpenRouterReranker

        reranker = OpenRouterReranker(config)
    elif config.rerank_provider == "local":
        from open_notebook.ai.guguta.local_retrieval import LocalReranker

        reranker = LocalReranker(config)
    else:
        reranker = None
    app.state.guguta_search = SearchService(
        engine,
        embedding_provider,
        max_vector_distance=config.vector_max_distance,
        reranker=reranker,
        candidate_limit=config.retrieval_candidates,
    )
    app.state.guguta_chat = ChatService(
        engine,
        app.state.guguta_search,
        get_chat_provider(config.chat_provider, config),
        total_timeout_seconds=config.chat_total_timeout_seconds,
    )
    app.state.guguta_chat._attachments = app.state.guguta_attachments
    if config.chat_provider == "openrouter" and config.chat_pdf_images:
        from api.services.guguta.pdf_evidence import PdfPageEvidence
        app.state.guguta_chat._pdf_evidence = PdfPageEvidence(
            engine, FilesystemStorage(config.storage_root),
            max_pages=config.chat_pdf_image_max_pages,
        )
    if config.chat_provider == "openrouter" and config.chat_agent_enabled:
        from api.services.guguta.chat_agent import NotebookChatAgent

        app.state.guguta_chat._agent = NotebookChatAgent(
            app.state.guguta_search, app.state.guguta_chat._pdf_evidence,
            max_rounds=config.chat_agent_max_rounds,
            max_calls=config.chat_agent_max_tool_calls,
            max_images=config.chat_agent_max_images,
        )
    app.state.guguta_notes = NotesService(engine)
    app.state.guguta_audio_overviews = AudioOverviewService(
        engine, FilesystemStorage(config.storage_root)
    )
    app.state.guguta_flashcards = FlashcardService(engine, config)
    app.state.guguta_quizzes = QuizService(engine, config)
    app.state.guguta_speech = SpeechService(
        config.parakeet_asr_base_url,
        timeout_seconds=config.parakeet_asr_timeout_seconds,
        max_audio_mib=config.parakeet_asr_max_audio_mib,
    )
    app.state.guguta_voice = VoiceService(engine, app.state.guguta_search)
    app.state.guguta_catalog = CatalogService(
        engine, quota_mib_per_user=config.quota_mib_per_user
    )
    app.state.guguta_state_codec = SignedStateCodec(config.server_secret)
    if config.auth_mode == "oidc" and config.oidc_issuer:
        from open_notebook.auth.guguta.oidc import OidcClient, OidcConfig

        app.state.guguta_oidc = OidcClient(
            OidcConfig(
                issuer=config.oidc_issuer,
                client_id=config.oidc_client_id,
                client_secret=config.oidc_client_secret,
                redirect_uri=config.oidc_redirect_uri,
            )
        )
    app.state.guguta_sharing = SharingService(
        engine, quota_mib_per_user=config.quota_mib_per_user
    )
    from open_notebook.auth.guguta.crypto import CredentialCrypto

    app.state.guguta_admin = AdminService(
        engine,
        CredentialCrypto(
            config.credential_encryption_keys, config.credential_key_primary_id
        ),
    )

    @app.on_event("shutdown")
    async def _dispose() -> None:
        await engine.dispose()

    @app.on_event("startup")
    async def _startup_checks() -> None:
        if (
            config.environment not in ("development", "ci")
            and config.auth_mode == "test"
        ):
            raise RuntimeError("test authentication refused outside development/ci")

    @app.middleware("http")
    async def session_middleware(request: Request, call_next: Any) -> Any:
        # Resolve actor from the session cookie (server-side truth only).
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            actor = await app.state.guguta_sessions.resolve_actor(token)
            if actor is not None:
                request.state.guguta_actor = actor
            # Cookie-based mutations require Origin match + CSRF header (ADR-0003).
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                origin = request.headers.get("origin")
                allowed = request.app.state.guguta_config.cors_origins
                if origin is not None and origin not in allowed:
                    return _error(
                        "origin_rejected",
                        "Origine neacceptată.",
                        403,
                        request.headers.get("x-request-id", "-"),
                    )
                is_login_route = request.url.path.startswith(_CSRF_EXEMPT_PREFIXES)
                is_readonly_post = request.url.path.endswith(("/search", "/preview"))
                if (
                    not is_login_route
                    and not is_readonly_post
                    and not app.state.guguta_sessions.verify_csrf(
                        token, request.headers.get(CSRF_HEADER)
                    )
                ):
                    return _error(
                        "csrf_required",
                        "Token CSRF lipsă sau invalid.",
                        403,
                        request.headers.get("x-request-id", "-"),
                    )
        request_id = request.headers.get("x-request-id", "-")
        response = await call_next(request)
        response.headers.setdefault("x-request-id", request_id)
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}  # liveness: process is up

    @app.get("/versionz")
    async def versionz() -> dict[str, str]:
        """Release identification — no secrets (R102; GHID §10.3)."""
        import os

        return {
            "service": "guguta-api",
            "version": "0.1.0",
            "commit": os.environ.get("GUGUTA_COMMIT", "unknown"),
        }

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        # Readiness: schema reachable with the runtime role (worker/AI excluded;
        # an unavailable LLM must not restart the process, GHID §14).
        try:
            async with engine.connect() as conn:
                version = (
                    await conn.execute(text("SELECT version_num FROM guguta_alembic"))
                ).scalar_one()
            return JSONResponse(content={"status": "ok", "schema": version})
        except Exception:
            return JSONResponse(status_code=503, content={"status": "db-unreachable"})

    app.include_router(auth_router)
    app.include_router(notebooks_router)
    app.include_router(sources_router)
    app.include_router(jobs_router)
    app.include_router(search_router)
    app.include_router(speech_router)
    app.include_router(voice_router)
    app.include_router(chat_router)
    app.include_router(notes_router)
    app.include_router(audio_overviews_router)
    app.include_router(flashcards_router)
    app.include_router(quizzes_router)
    app.include_router(admin_catalog_router)
    app.include_router(catalog_router)
    app.include_router(shares_router)
    app.include_router(imports_router)
    app.include_router(admin_router)
    app.include_router(reports_router)

    @app.exception_handler(AuthenticationError)
    async def auth_error(request: Request, exc: AuthenticationError) -> JSONResponse:
        return _error(
            "unauthenticated",
            "Autentificare necesară.",
            401,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(InvalidInputError)
    async def invalid_input(request: Request, exc: InvalidInputError) -> JSONResponse:
        return _error(
            "invalid", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(SpeechValidation)
    async def speech_validation(
        request: Request, exc: SpeechValidation
    ) -> JSONResponse:
        return _error(
            "invalid_audio", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(SpeechUnavailable)
    async def speech_unavailable(
        request: Request, exc: SpeechUnavailable
    ) -> JSONResponse:
        return _error(
            "speech_unavailable",
            str(exc),
            503,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(VoiceUnavailable)
    async def voice_unavailable(request: Request, exc: VoiceUnavailable) -> JSONResponse:
        return _error(
            "voice_unavailable", str(exc), 503, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(VoiceRateLimited)
    async def voice_rate_limited(request: Request, exc: VoiceRateLimited) -> JSONResponse:
        response = _error(
            "voice_rate_limited", str(exc), 429, request.headers.get("x-request-id", "-")
        )
        response.headers["Retry-After"] = "30"
        return response

    @app.exception_handler(OidcError)
    async def oidc_error(request: Request, exc: OidcError) -> JSONResponse:
        return _error(
            "auth_provider",
            "Autentificarea a eșuat.",
            502,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(ActorDenied)
    async def denied_error(request: Request, exc: ActorDenied) -> JSONResponse:
        return _error(
            "forbidden",
            "Acțiune nepermisă.",
            403,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(NotFoundError)
    async def not_found_error(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error(
            "not_found",
            "Resursa nu există.",
            404,
            request.headers.get("x-request-id", "-"),
        )

    from open_notebook.ai.guguta.openrouter import OpenRouterError

    @app.exception_handler(OpenRouterError)
    async def openrouter_error(request: Request, exc: OpenRouterError) -> JSONResponse:
        return _error(
            "ai_provider", str(exc), 502, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(OpenNotebookError)
    async def domain_error(request: Request, exc: OpenNotebookError) -> JSONResponse:
        return _error(
            "error", "Eroare internă.", 500, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(NotebookNotFound)
    async def not_found(request: Request, exc: NotebookNotFound) -> JSONResponse:
        # 404 also for foreign objects — no existence disclosure (GHID §5.1).
        return _error(
            "not_found",
            "Resursa nu există.",
            404,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(NotebookValidation)
    async def validation_error(
        request: Request, exc: NotebookValidation
    ) -> JSONResponse:
        return _error(
            "invalid", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(SourceNotFound)
    async def source_not_found(request: Request, exc: SourceNotFound) -> JSONResponse:
        return _error(
            "not_found",
            "Resursa nu există.",
            404,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(SourceValidation)
    async def source_validation(
        request: Request, exc: SourceValidation
    ) -> JSONResponse:
        return _error(
            "invalid", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(QuotaExceeded)
    async def quota_exceeded(request: Request, exc: QuotaExceeded) -> JSONResponse:
        return _error(
            "quota_exceeded", str(exc), 429, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(TemplateNotFound)
    async def template_not_found(
        request: Request, exc: TemplateNotFound
    ) -> JSONResponse:
        return _error(
            "not_found",
            "Resursa nu există.",
            404,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(CatalogValidation)
    async def catalog_validation(
        request: Request, exc: CatalogValidation
    ) -> JSONResponse:
        return _error(
            "invalid", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(RetiredTemplate)
    async def retired_template(request: Request, exc: RetiredTemplate) -> JSONResponse:
        return _error(
            "retired", str(exc), 409, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(ShareNotFound)
    async def share_not_found(request: Request, exc: ShareNotFound) -> JSONResponse:
        message = str(exc) or "Resursa nu există."
        return _error(
            "not_found", message, 404, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(ShareRevoked)
    async def share_revoked(request: Request, exc: ShareRevoked) -> JSONResponse:
        return _error(
            "share_revoked", str(exc), 409, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(ShareExpired)
    async def share_expired(request: Request, exc: ShareExpired) -> JSONResponse:
        return _error(
            "share_expired", str(exc), 410, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(ShareValidation)
    async def share_validation(request: Request, exc: ShareValidation) -> JSONResponse:
        return _error(
            "invalid", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(ShareQuotaExceeded)
    async def share_quota(request: Request, exc: ShareQuotaExceeded) -> JSONResponse:
        return _error(
            "quota_exceeded", str(exc), 429, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(NoteNotFound)
    async def note_not_found(request: Request, exc: NoteNotFound) -> JSONResponse:
        return _error(
            "not_found",
            "Resursa nu există.",
            404,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(NoteValidation)
    async def note_validation(request: Request, exc: NoteValidation) -> JSONResponse:
        return _error(
            "invalid", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    from open_notebook.jobs.guguta.parsing import ExtractionError

    @app.exception_handler(ExtractionError)
    async def extraction_error(request: Request, exc: ExtractionError) -> JSONResponse:
        return _error(
            "unsupported", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(ChatValidation)
    async def chat_validation(request: Request, exc: ChatValidation) -> JSONResponse:
        return _error(
            "invalid", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(SourcesRequired)
    async def sources_required(request: Request, exc: SourcesRequired) -> JSONResponse:
        return _error(
            "sources_required", str(exc), 422, request.headers.get("x-request-id", "-")
        )

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict(
        request: Request, exc: IdempotencyConflict
    ) -> JSONResponse:
        return _error(
            "idempotency_conflict",
            str(exc),
            409,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(ChatSessionNotFound)
    async def chat_session_missing(
        request: Request, exc: ChatSessionNotFound
    ) -> JSONResponse:
        return _error(
            "not_found",
            "Resursa nu există.",
            404,
            request.headers.get("x-request-id", "-"),
        )

    @app.exception_handler(ChatProviderUnavailable)
    async def provider_unavailable(
        request: Request, exc: ChatProviderUnavailable
    ) -> JSONResponse:
        return _error(
            "provider_unavailable",
            str(exc),
            502,
            request.headers.get("x-request-id", "-"),
        )

    return app


# The `app` attribute is built lazily via module __getattr__ (PEP 562) so the
# module can be imported without a runtime configuration (tests import
# create_guguta_app directly). IMPORTANT: `app` must NOT be pre-assigned —
# a module-level `app = None` would shadow __getattr__ and uvicorn would
# receive None as the ASGI app.

_config = None


def _build_default_app() -> FastAPI:
    global _config
    _config = GugutaConfig()
    return create_guguta_app(_config)


def __getattr__(name: str) -> Any:
    if name == "app":
        value = _build_default_app()
        globals()["app"] = value
        return value
    raise AttributeError(name)
