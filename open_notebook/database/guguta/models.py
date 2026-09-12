"""SQLAlchemy 2 models for the Guguță schema (specificații Â§9, ADR-0001/0006).

Naming and relations follow SPECIFICATII_GUGUTA.md Â§9. UUIDs are generated
server-side (Python ``uuid4`` at flush). All timestamps are UTC timestamptz.

Ownership model (ADR-0007):
- Personal tables carry ``owner_id`` / ``created_by`` and are RLS-protected.
- Derived tables (notebook_sources, chat_messages, citations, notes, chunksâ€¦)
  inherit ownership through joins â€” policies use EXISTS over those joins and
  no denormalized owner column is added.

Immutability (ADR-0006):
- ``MaterialVersion.source_asset_id`` is set once (trigger blocks rebinds).
- Published ``TemplateVersion.manifest`` is immutable (trigger blocks edits).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    literal_column,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class GugutaBase(DeclarativeBase):
    """Declarative base for the Guguță PostgreSQL schema."""


def text_literal(sql: str) -> Any:
    """Small helper for partial-index WHERE clauses in table args."""
    return literal_column(sql)

def sa_true() -> Any:
    """server_default for boolean True."""
    return sa_text("true")


def sa_false() -> Any:
    """server_default for boolean False."""
    return sa_text("false")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )


def _ts() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _ts_opt() -> Mapped[Optional[datetime]]:
    return mapped_column(DateTime(timezone=True), nullable=True)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# --------------------------------------------------------------------------
# Identity (ADR-0003)
# --------------------------------------------------------------------------


class User(GugutaBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )  # active | suspended | deleted
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, server_default="{user}"
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','suspended','deleted')", name="ck_users_status"
        ),
        CheckConstraint(
            "roles <@ ARRAY['user','catalog_editor','admin']::varchar[] "
            "AND array_length(roles, 1) >= 1",
            name="ck_users_roles",
        ),
        Index(
            "ux_users_email",
            "email",
            unique=True,
            postgresql_where=text_literal("email IS NOT NULL"),
        ),
    )


class Identity(GugutaBase):
    """OIDC association â€” unique on issuer + subject, never email alone."""

    __tablename__ = "identities"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    created_at: Mapped[datetime] = _ts()
    last_login_at: Mapped[Optional[datetime]] = _ts_opt()

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="ux_identities_issuer_subject"),
    )


class Session(GugutaBase):
    """Opaque server-side session; only the token hash is stored."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = _ts_opt()
    revoked_at: Mapped[Optional[datetime]] = _ts_opt()

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_sessions_expiry"),
        Index("ix_sessions_user", "user_id"),
    )


# --------------------------------------------------------------------------
# Catalog (ADR-0006) â€” created before notebooks so notebook FKs are simple
# --------------------------------------------------------------------------


class Template(GugutaBase):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    class_level: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    discipline: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    language: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ro", server_default="ro"
    )
    edition: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rights_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','published','retired')", name="ck_templates_status"
        ),
    )


class TemplateVersion(GugutaBase):
    __tablename__ = "template_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    published_at: Mapped[Optional[datetime]] = _ts_opt()
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("template_id", "version", name="ux_template_versions"),
        CheckConstraint("version >= 1", name="ck_template_versions_version"),
        CheckConstraint(
            "status IN ('draft','published','retired')",
            name="ck_template_versions_status",
        ),
    )


class TemplateMaterial(GugutaBase):
    __tablename__ = "template_materials"

    id: Mapped[uuid.UUID] = _uuid_pk()
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    material_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "template_version_id", "position", name="ux_template_materials_pos"
        ),
        UniqueConstraint(
            "template_version_id",
            "material_version_id",
            name="ux_template_materials_mv",
        ),
    )


# --------------------------------------------------------------------------
# Materials (ADR-0004, ADR-0006)
# --------------------------------------------------------------------------


class SourceAsset(GugutaBase):
    """Immutable bytes/text; grants no access by itself."""

    __tablename__ = "source_assets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # file | text
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_name: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    retention_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="retained", server_default="retained"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint("kind IN ('file','text')", name="ck_source_assets_kind"),
        CheckConstraint("byte_size >= 0", name="ck_source_assets_size"),
        CheckConstraint(
            "retention_status IN ('retained','gc_candidate','deleted')",
            name="ck_source_assets_retention",
        ),
        CheckConstraint(
            "(kind = 'file' AND storage_key IS NOT NULL) OR "
            "(kind = 'text' AND text_content IS NOT NULL)",
            name="ck_source_assets_payload",
        ),
        Index("ix_source_assets_sha256", "sha256"),
    )


class MaterialVersion(GugutaBase):
    """Versioned content + provenance; published versions never mutate."""

    __tablename__ = "material_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_material_versions_version"),
    )


class DigitalNotebook(GugutaBase):
    __tablename__ = "digital_notebooks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default="personal", server_default="personal"
    )  # personal | empty | template | import
    current_template_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    origin_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # FK to share_snapshots added in migration after share tables
    context_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    archived_at: Mapped[Optional[datetime]] = _ts_opt()
    # Fixarea „sus" în lista proprietarului: NULL = nefixat. Ordinea din listă
    # pune carnetele fixate primele, apoi sortarea cerută (vezi
    # api/services/guguta/notebooks.py).
    pinned_at: Mapped[Optional[datetime]] = _ts_opt()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','archived','deleted')", name="ck_notebooks_status"
        ),
        CheckConstraint(
            "origin IN ('personal','empty','template','import')",
            name="ck_notebooks_origin",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_notebooks_title"),
        CheckConstraint("context_revision >= 1", name="ck_notebooks_revision"),
        Index("ix_notebooks_owner", "owner_id", "status"),
    )


class NotebookSource(GugutaBase):
    """Personal association notebook â†” material version; local ID per copy."""

    __tablename__ = "notebook_sources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    notebook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("digital_notebooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    material_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    local_name: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_for_chat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_true()
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploading", server_default="uploading"
    )  # uploading | processing | ready | error | replaced
    status_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        UniqueConstraint("notebook_id", "position", name="ux_notebook_sources_pos"),
        CheckConstraint(
            "status IN ('uploading','processing','ready','error','replaced')",
            name="ck_notebook_sources_status",
        ),
        Index("ix_notebook_sources_notebook", "notebook_id"),
    )


# --------------------------------------------------------------------------
# Processing artifacts (ADR-0001/0002)
# --------------------------------------------------------------------------


class EmbeddingSpace(GugutaBase):
    """Vector configuration; incompatible spaces are never mixed (A27)."""

    __tablename__ = "embedding_spaces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(255), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_strategy: Mapped[str] = mapped_column(
        String(30), nullable=False, default="cosine", server_default="cosine"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint("dimension > 0 AND dimension <= 20000", name="ck_emb_dim"),
        CheckConstraint(
            "distance_strategy IN ('cosine','l2','inner_product')",
            name="ck_emb_distance",
        ),
        Index(
            "ux_embedding_spaces_active",
            "is_active",
            unique=True,
            postgresql_where=text_literal("is_active"),
        ),
    )


class ProcessingArtifact(GugutaBase):
    __tablename__ = "processing_artifacts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    material_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    parser: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    chunker: Mapped[str] = mapped_column(String(100), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(100), nullable=False)
    chunk_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_overlap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", server_default="running"
    )
    result_checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    completed_at: Mapped[Optional[datetime]] = _ts_opt()

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','complete','failed')", name="ck_artifacts_status"
        ),
        Index("ix_artifacts_mv", "material_version_id"),
    )


class Chunk(GugutaBase):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("artifact_id", "position", name="ux_chunks_pos"),
        CheckConstraint("length(btrim(text)) > 0", name="ck_chunks_text"),
    )


class Embedding(GugutaBase):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    embedding_space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("embedding_spaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    embedding: Mapped[Any] = mapped_column(Vector(), nullable=False)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_space_id", name="ux_embeddings_chunk"),
    )


# --------------------------------------------------------------------------
# Share / import (ADR-0006)
# --------------------------------------------------------------------------


class ShareSnapshot(GugutaBase):
    __tablename__ = "share_snapshots"

    id: Mapped[uuid.UUID] = _uuid_pk()
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    notebook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("digital_notebooks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _ts()
    revoked_at: Mapped[Optional[datetime]] = _ts_opt()

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','revoked')", name="ck_share_snapshots_status"
        ),
        CheckConstraint("schema_version >= 1", name="ck_share_snapshots_schema"),
    )


class ShareMaterial(GugutaBase):
    __tablename__ = "share_materials"

    id: Mapped[uuid.UUID] = _uuid_pk()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("share_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    material_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "position", name="ux_share_materials_pos"),
        UniqueConstraint(
            "snapshot_id", "material_version_id", name="ux_share_materials_mv"
        ),
    )


class ShareCredential(GugutaBase):
    """Access tokens for the same snapshot; only hashes are stored."""

    __tablename__ = "share_credentials"

    id: Mapped[uuid.UUID] = _uuid_pk()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("share_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # link | code
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = _ts()
    revoked_at: Mapped[Optional[datetime]] = _ts_opt()

    __table_args__ = (
        CheckConstraint("kind IN ('link','code')", name="ck_share_credentials_kind"),
    )


class ShareImport(GugutaBase):
    __tablename__ = "share_imports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("share_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    notebook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("digital_notebooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint(
            "recipient_id", "idempotency_key", name="ux_share_imports_idem"
        ),
    )


class IdempotencyRecord(GugutaBase):
    """Actor + operation + key unique; same key with other payload conflicts."""

    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    result_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "operation_type",
            "idempotency_key",
            name="ux_idempotency_records",
        ),
    )


# --------------------------------------------------------------------------
# Chat (ADR-0005)
# --------------------------------------------------------------------------


class ChatSession(GugutaBase):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    notebook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("digital_notebooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (Index("ix_chat_sessions_notebook", "notebook_id"),)


class ChatMessage(GugutaBase):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # per-session ordering (UNIQUE(session_id, seq) — migration 0004)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="complete", server_default="complete"
    )
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system','error')", name="ck_messages_role"
        ),
        CheckConstraint(
            "status IN ('pending','streaming','complete','cancelled','failed')",
            name="ck_messages_status",
        ),
        Index("ix_chat_messages_session", "session_id", "seq"),
    )


class Citation(GugutaBase):
    """Historic citation; survives association removal via snapshot columns.

    ``notebook_source_id``/``chunk_id``/``material_version_id`` become NULL if
    the referenced row disappears (SET NULL) â€” the citation then renders as
    â€žSursă eliminatăâ€ without exposing any other user's resources.
    """

    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    notebook_source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notebook_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    material_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_citations_message", "message_id"),)


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------


class Note(GugutaBase):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    notebook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("digital_notebooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (Index("ix_notes_notebook", "notebook_id"),)


# --------------------------------------------------------------------------
# Jobs, outbox, audit (ADR-0002)
# --------------------------------------------------------------------------


class ProcessingJob(GugutaBase):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lease_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[Optional[datetime]] = _ts_opt()
    heartbeat_at: Mapped[Optional[datetime]] = _ts_opt()
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    deadline: Mapped[Optional[datetime]] = _ts_opt()
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _updated_at()
    completed_at: Mapped[Optional[datetime]] = _ts_opt()

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','claimed','running','succeeded','failed','cancelled')",
            name="ck_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts"),
        Index("ix_jobs_claim", "status", "run_after"),
        Index("ix_jobs_actor", "actor_id"),
    )


class OutboxEvent(GugutaBase):
    """Transactional outbox for future external publication (ADR-0002 Â§5)."""

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = _ts()
    published_at: Mapped[Optional[datetime]] = _ts_opt()


class AuditEvent(GugutaBase):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    result: Mapped[str] = mapped_column(
        String(20), nullable=False, default="allowed", server_default="allowed"
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(
            "result IN ('allowed','denied','error')", name="ck_audit_result"
        ),
        Index("ix_audit_action", "action", "created_at"),
    )
