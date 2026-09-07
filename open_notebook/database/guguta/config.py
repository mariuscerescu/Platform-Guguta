"""Guguță runtime configuration (GHID §10.2).

Environment variables are prefixed with ``GUGUTA_``. No secret has a default
value here; development compose supplies local-only dev defaults explicitly.

Startup safety (R73-like behaviour, enforced from L1): in ``staging`` or
``production`` the configuration refuses test authentication mode, default
encryption secrets and wildcard origins. Full endpoint hardening lands in L2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "ci", "staging", "production"]
AuthMode = Literal["test", "oidc"]

_DEV_ENVIRONMENTS: tuple[str, ...] = ("development", "ci")


class GugutaConfig(BaseSettings):
    """Validated configuration for API and worker processes."""

    model_config = SettingsConfigDict(
        env_prefix="GUGUTA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "development"
    auth_mode: AuthMode = "test"

    # Separate roles per process (ADR-0007). The migrator URL is only used by
    # the release migration job, never by API/worker runtime.
    database_url_migrator: str = ""
    database_url_api: str = ""
    database_url_worker: str = ""

    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30

    # Private storage root for the filesystem backend (ADR-0004). Must be
    # outside any web-served directory.
    storage_root: str = "./guguta_storage"

    # Public origin of the deployment; no wildcard with credentials.
    public_origin: str = "http://localhost:3001"
    cors_origins: list[str] = ["http://localhost:3001", "http://localhost:3000"]

    # Working limits (GHID §10.2, calibrate before staging).
    max_upload_mib: int = 25
    max_pdf_pages: int = 300
    max_sources_per_notebook: int = 20
    quota_mib_per_user: int = 1024
    max_concurrent_jobs_per_user: int = 2
    chat_total_timeout_seconds: int = 120

    # --- Identity / sessions (ADR-0003) ---
    # server_secret signs CSRF/state material; MUST come from the environment
    # outside development. No default secret is treated as valid in staging.
    server_secret: str = "dev-only-insecure-secret-change-me"
    session_absolute_ttl_hours: int = 12
    session_inactivity_ttl_minutes: int = 120

    # OIDC provider (required when auth_mode=oidc).
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""

    # Credential encryption (L5): dict of key_id -> secret; the primary id
    # encrypts new payloads, the others allow rotation fallbacks.
    credential_key_primary_id: str = "k1"
    credential_encryption_keys: dict[str, str] = {
        "k1": "dev-only-insecure-key-change-me"
    }

    # API surface mode: guguta = only /api/v1 (+health); legacy = upstream.
    api_mode: Literal["guguta", "legacy"] = "guguta"

    # --- Materials pipeline (L3, GHID §6) ---
    chunk_size_chars: int = 2000
    chunk_overlap_chars: int = 200
    embedding_provider: str = "hash"  # mock until D-02 closes
    embedding_dimension: int = 8
    vector_max_distance: float = 0.9  # cosine-distance cutoff for retrieval
    chat_provider: str = "mock"  # mock until D-02 closes
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_embedding_model: str = "nvidia/nemotron-3-embed-1b:free"
    openrouter_embedding_revision: str = "openrouter-2026-09-07"
    openrouter_rerank_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
    openrouter_chat_model: str = "minimax/minimax-m3:free"
    rerank_provider: Literal["none", "openrouter"] = "none"
    retrieval_candidates: int = Field(default=24, ge=6, le=50)
    openrouter_timeout_seconds: float = Field(default=60, gt=0, le=300)
    openrouter_max_retries: int = Field(default=1, ge=0, le=3)
    openrouter_embedding_batch_size: int = Field(default=16, ge=1, le=32)
    openrouter_max_output_tokens: int = Field(default=1500, ge=128, le=8192)
    job_lease_seconds: int = 300
    job_poll_seconds: float = 2.0
    job_worker_name: str = "worker-1"

    @model_validator(mode="after")
    def _refuse_unsafe_production_config(self) -> "GugutaConfig":
        if self.chat_provider not in ("mock", "openrouter") or self.embedding_provider not in ("hash", "openrouter"):
            raise ValueError("unknown Guguță AI provider")
        if "openrouter" in (self.chat_provider, self.embedding_provider, self.rerank_provider):
            if not self.openrouter_api_key.get_secret_value():
                raise ValueError("GUGUTA_OPENROUTER_API_KEY is required")
            if self.embedding_provider == "openrouter" and self.embedding_dimension != 2048:
                raise ValueError("Nemotron embeddings require GUGUTA_EMBEDDING_DIMENSION=2048")
        if self.environment in _DEV_ENVIRONMENTS:
            return self
        problems: list[str] = []
        if self.auth_mode == "test":
            problems.append("GUGUTA_AUTH_MODE=test is refused outside development/ci")
        if not self.database_url_api or not self.database_url_worker:
            problems.append("runtime database URLs are required outside development/ci")
        origins = [o.strip() for o in self.cors_origins]
        if not origins or any(not o for o in origins):
            problems.append("at least one explicit CORS origin is required")
        if any(o == "*" for o in origins):
            problems.append("wildcard CORS origin is refused")
        if any(not o.startswith("https://") for o in origins):
            problems.append("CORS origins must use https outside development/ci")
        if not self.public_origin.startswith("https://"):
            problems.append("GUGUTA_PUBLIC_ORIGIN must use https outside development/ci")
        # F14: fail-closed on secrets — empty, short or dev-default values
        if not self.server_secret or len(self.server_secret) < 16:
            problems.append("GUGUTA_SERVER_SECRET must be set (min 16 chars)")
        elif self.server_secret == "dev-only-insecure-secret-change-me":
            problems.append("GUGUTA_SERVER_SECRET must not be the development default")
        if not self.credential_encryption_keys:
            problems.append("GUGUTA_CREDENTIAL_ENCRYPTION_KEYS must be set")
        else:
            if self.credential_key_primary_id not in self.credential_encryption_keys:
                problems.append(
                    f"primary credential key '{self.credential_key_primary_id}' "
                    "is not in GUGUTA_CREDENTIAL_ENCRYPTION_KEYS"
                )
            for kid, secret in self.credential_encryption_keys.items():
                if not secret or len(secret) < 16 or secret.startswith("dev-only-insecure"):
                    problems.append(
                        f"credential encryption key '{kid}' is missing or insecure"
                    )
        if self.auth_mode == "oidc":
            if not (self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret):
                problems.append("OIDC issuer/client/secret are required when auth_mode=oidc")
            elif not self.oidc_issuer.startswith("https://"):
                problems.append("OIDC issuer must use https outside development/ci")
            if not self.oidc_redirect_uri:
                problems.append("OIDC redirect URI is required when auth_mode=oidc")
            elif not self.oidc_redirect_uri.startswith("https://"):
                problems.append("OIDC redirect URI must use https outside development/ci")
        # F14: simulated AI providers are refused for real users
        if self.chat_provider in ("mock",):
            problems.append("mock chat provider is refused outside development/ci")
        if self.embedding_provider in ("mock", "hash"):
            problems.append("hash embedding provider is refused outside development/ci")
        if self.api_mode != "guguta":
            problems.append("legacy API surface is refused outside development/ci")
        if problems:
            raise ValueError("unsafe configuration: " + "; ".join(problems))
        return self
