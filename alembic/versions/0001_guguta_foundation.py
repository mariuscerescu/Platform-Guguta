"""Guguță foundation schema (ADR-0001/0006/0007).

Tables are created from the SQLAlchemy models (single source of truth); this
migration then adds everything models cannot express: the pgvector extension,
runtime roles, the extra origin FK, integrity triggers, row-level security
policies and runtime grants.

Rules encoded here:
- RLS is ENABLED (not FORCEd): api/worker runtime roles are non-owners, so
  policies apply to them; the migrator (owner) keeps migration access without
  an actor context. Verified by tests, not assumed.
- Actor context is transaction-local via set_config('app.actor_id', ..., true).
- The share context (app.share_context) is set only by server code after token
  validation and grants SELECT on one active snapshot's materials.
- Published template versions and material source bindings are immutable.
- Embedding dimensions are validated against embedding_spaces.

Revision ID: 0001
Revises:
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from open_notebook.database.guguta.models import GugutaBase

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Helper SQL
# ---------------------------------------------------------------------------

_ROLES_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guguta_api') THEN
        CREATE ROLE guguta_api LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guguta_worker') THEN
        CREATE ROLE guguta_worker LOGIN;
    END IF;
END $$;
"""

_FUNCTIONS_SQL = [
    # Actor context readers; NULL when unset (-> policies deny).
    """
    CREATE OR REPLACE FUNCTION guguta_actor() RETURNS uuid
    LANGUAGE sql STABLE AS $$
        SELECT NULLIF(current_setting('app.actor_id', true), '')::uuid
    $$;
    """,
    """
    CREATE OR REPLACE FUNCTION guguta_share_context() RETURNS uuid
    LANGUAGE sql STABLE AS $$
        SELECT NULLIF(current_setting('app.share_context', true), '')::uuid
    $$;
    """,
    # updated_at maintenance
    """
    CREATE OR REPLACE FUNCTION guguta_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END $$;
    """,
    # Embedding dimension integrity (A27)
    """
    CREATE OR REPLACE FUNCTION guguta_validate_embedding_dimension() RETURNS trigger
    LANGUAGE plpgsql STABLE AS $$
    DECLARE
        required_dim integer;
    BEGIN
        SELECT dimension INTO required_dim FROM embedding_spaces
        WHERE id = NEW.embedding_space_id;
        IF required_dim IS NULL THEN
            RAISE EXCEPTION 'embedding_space % does not exist', NEW.embedding_space_id;
        END IF;
        IF vector_dims(NEW.embedding) <> required_dim THEN
            RAISE EXCEPTION 'embedding dimension % does not match embedding_space dimension %',
                vector_dims(NEW.embedding), required_dim;
        END IF;
        RETURN NEW;
    END $$;
    """,
    # Published template versions are immutable (A14, A21)
    """
    CREATE OR REPLACE FUNCTION guguta_lock_published_template() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.status = 'published' THEN
            IF NEW.manifest IS DISTINCT FROM OLD.manifest
               OR NEW.version IS DISTINCT FROM OLD.version
               OR NEW.template_id IS DISTINCT FROM OLD.template_id THEN
                RAISE EXCEPTION 'published template version % is immutable; create a new version', OLD.id;
            END IF;
        END IF;
        RETURN NEW;
    END $$;
    """,
    # Material versions never rebind to another asset (A21)
    """
    CREATE OR REPLACE FUNCTION guguta_lock_material_source() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.source_asset_id IS DISTINCT FROM OLD.source_asset_id THEN
            RAISE EXCEPTION 'material_version % cannot rebind to another source asset; create a new version', OLD.id;
        END IF;
        RETURN NEW;
    END $$;
    """,
]

_TRIGGERS_SQL = [
    "CREATE TRIGGER trg_users_touch BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();",
    "CREATE TRIGGER trg_notebooks_touch BEFORE UPDATE ON digital_notebooks FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();",
    "CREATE TRIGGER trg_notebook_sources_touch BEFORE UPDATE ON notebook_sources FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();",
    "CREATE TRIGGER trg_chat_sessions_touch BEFORE UPDATE ON chat_sessions FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();",
    "CREATE TRIGGER trg_notes_touch BEFORE UPDATE ON notes FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();",
    "CREATE TRIGGER trg_jobs_touch BEFORE UPDATE ON processing_jobs FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();",
    "CREATE TRIGGER trg_templates_touch BEFORE UPDATE ON templates FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();",
    "CREATE TRIGGER trg_embeddings_dim BEFORE INSERT OR UPDATE OF embedding ON embeddings FOR EACH ROW EXECUTE FUNCTION guguta_validate_embedding_dimension();",
    "CREATE TRIGGER trg_template_versions_lock BEFORE UPDATE ON template_versions FOR EACH ROW EXECUTE FUNCTION guguta_lock_published_template();",
    "CREATE TRIGGER trg_material_versions_lock BEFORE UPDATE ON material_versions FOR EACH ROW EXECUTE FUNCTION guguta_lock_material_source();",
]

# (table, policy_name, command, to_role, using, with_check)
# command: SELECT | INSERT | UPDATE | DELETE | ALL
_P = tuple[str, str, str, str, str | None, str | None]


def _policies() -> list[_P]:
    notebook_owned = (
        "EXISTS (SELECT 1 FROM digital_notebooks dn WHERE dn.id = {col} "
        "AND dn.owner_id = guguta_actor())"
    )
    src_via_notebook = (
        "EXISTS (SELECT 1 FROM material_versions mv "
        "JOIN notebook_sources ns ON ns.material_version_id = mv.id "
        "JOIN digital_notebooks dn ON dn.id = ns.notebook_id "
        "WHERE mv.source_asset_id = source_assets.id AND dn.owner_id = guguta_actor())"
    )
    src_via_share = (
        "EXISTS (SELECT 1 FROM share_materials sm "
        "JOIN share_snapshots ss ON ss.id = sm.snapshot_id "
        "JOIN material_versions mv2 ON mv2.id = sm.material_version_id "
        "WHERE mv2.source_asset_id = source_assets.id AND ss.status = 'active' "
        "AND ss.id = guguta_share_context())"
    )
    src_via_template = (
        "EXISTS (SELECT 1 FROM material_versions mv3 "
        "JOIN template_materials tm ON tm.material_version_id = mv3.id "
        "JOIN template_versions tv ON tv.id = tm.template_version_id "
        "WHERE mv3.source_asset_id = source_assets.id AND tv.status = 'published')"
    )
    mv_via_notebook = (
        "EXISTS (SELECT 1 FROM notebook_sources ns "
        "JOIN digital_notebooks dn ON dn.id = ns.notebook_id "
        "WHERE ns.material_version_id = material_versions.id AND dn.owner_id = guguta_actor())"
    )
    mv_via_share = (
        "EXISTS (SELECT 1 FROM share_materials sm "
        "JOIN share_snapshots ss ON ss.id = sm.snapshot_id "
        "WHERE sm.material_version_id = material_versions.id "
        "AND ss.status = 'active' AND ss.id = guguta_share_context())"
    )
    mv_via_template = (
        "EXISTS (SELECT 1 FROM template_materials tm "
        "JOIN template_versions tv ON tv.id = tm.template_version_id "
        "WHERE tm.material_version_id = material_versions.id AND tv.status = 'published')"
    )
    artifact_via_notebook = (
        "EXISTS (SELECT 1 FROM material_versions mv "
        "JOIN notebook_sources ns ON ns.material_version_id = mv.id "
        "JOIN digital_notebooks dn ON dn.id = ns.notebook_id "
        "WHERE mv.id = processing_artifacts.material_version_id AND dn.owner_id = guguta_actor())"
    )
    chunk_via_notebook = (
        "EXISTS (SELECT 1 FROM processing_artifacts pa "
        "JOIN material_versions mv ON mv.id = pa.material_version_id "
        "JOIN notebook_sources ns ON ns.material_version_id = mv.id "
        "JOIN digital_notebooks dn ON dn.id = ns.notebook_id "
        "WHERE pa.id = chunks.artifact_id AND dn.owner_id = guguta_actor())"
    )
    emb_via_notebook = (
        "EXISTS (SELECT 1 FROM chunks c "
        "JOIN processing_artifacts pa ON pa.id = c.artifact_id "
        "JOIN material_versions mv ON mv.id = pa.material_version_id "
        "JOIN notebook_sources ns ON ns.material_version_id = mv.id "
        "JOIN digital_notebooks dn ON dn.id = ns.notebook_id "
        "WHERE c.id = embeddings.chunk_id AND dn.owner_id = guguta_actor())"
    )
    msg_via_notebook = (
        "EXISTS (SELECT 1 FROM chat_sessions cs "
        "JOIN digital_notebooks dn ON dn.id = cs.notebook_id "
        "WHERE cs.id = chat_messages.session_id AND dn.owner_id = guguta_actor())"
    )
    cit_via_notebook = (
        "EXISTS (SELECT 1 FROM chat_messages cm "
        "JOIN chat_sessions cs ON cs.id = cm.session_id "
        "JOIN digital_notebooks dn ON dn.id = cs.notebook_id "
        "WHERE cm.id = citations.message_id AND dn.owner_id = guguta_actor())"
    )
    ss_read = (
        "(author_id = guguta_actor() OR (status = 'active' AND id = guguta_share_context()))"
    )
    ss_via_author = "EXISTS (SELECT 1 FROM share_snapshots ss WHERE ss.id = {col} AND ss.author_id = guguta_actor())"
    tv_read = "(status = 'published' OR created_by = guguta_actor())"
    tv_via_template_read = (
        "EXISTS (SELECT 1 FROM template_versions tv WHERE tv.id = template_materials.template_version_id "
        "AND (tv.status = 'published' OR tv.created_by = guguta_actor()))"
    )

    rows: list[_P] = []

    # users / identities / sessions — self access only
    rows += [
        ("users", "p_users_self", "ALL", "guguta_api", "id = guguta_actor()", "id = guguta_actor()"),
        ("identities", "p_ident_self", "ALL", "guguta_api", "user_id = guguta_actor()", "user_id = guguta_actor()"),
        ("sessions", "p_sessions_self", "ALL", "guguta_api", "user_id = guguta_actor()", "user_id = guguta_actor()"),
    ]
    # digital_notebooks — owner full CRUD
    rows += [
        ("digital_notebooks", "p_nb_owner", "ALL", "guguta_api", "owner_id = guguta_actor()", "owner_id = guguta_actor()"),
        ("digital_notebooks", "p_nb_owner_w", "ALL", "guguta_worker", "owner_id = guguta_actor()", "owner_id = guguta_actor()"),
    ]
    # notebook_sources / notes / chat_sessions — via notebook
    for table, col in (("notebook_sources", "notebook_id"), ("notes", "notebook_id"), ("chat_sessions", "notebook_id")):
        exists = notebook_owned.format(col=col)
        rows += [
            (table, f"p_{table}_select", "SELECT", "guguta_api", exists, None),
            (table, f"p_{table}_insert", "INSERT", "guguta_api", None, exists),
            (table, f"p_{table}_update", "UPDATE", "guguta_api", exists, exists),
            (table, f"p_{table}_delete", "DELETE", "guguta_api", exists, None),
            (table, f"p_{table}_w_select", "SELECT", "guguta_worker", exists, None),
            (table, f"p_{table}_w_insert", "INSERT", "guguta_worker", None, exists),
            (table, f"p_{table}_w_update", "UPDATE", "guguta_worker", exists, exists),
        ]
    # chat_messages / citations — deeper joins
    for table, exists in (("chat_messages", msg_via_notebook), ("citations", cit_via_notebook)):
        rows += [
            (table, f"p_{table}_select", "SELECT", "guguta_api", exists, None),
            (table, f"p_{table}_insert", "INSERT", "guguta_api", None, exists),
            (table, f"p_{table}_update", "UPDATE", "guguta_api", exists, exists),
            (table, f"p_{table}_delete", "DELETE", "guguta_api", exists, None),
            (table, f"p_{table}_w_select", "SELECT", "guguta_worker", exists, None),
            (table, f"p_{table}_w_insert", "INSERT", "guguta_worker", None, exists),
        ]
    # source_assets — insert by creator; read only through authorized paths
    src_read = f"({src_via_notebook} OR {src_via_share} OR {src_via_template})"
    rows += [
        ("source_assets", "p_sa_insert", "INSERT", "guguta_api", None, "created_by = guguta_actor()"),
        ("source_assets", "p_sa_select", "SELECT", "guguta_api", src_read, None),
        ("source_assets", "p_sa_w_insert", "INSERT", "guguta_worker", None, "created_by = guguta_actor()"),
        ("source_assets", "p_sa_w_select", "SELECT", "guguta_worker", src_read, None),
    ]
    # material_versions — insert by creator; read via authorized paths
    mv_read = f"({mv_via_notebook} OR {mv_via_share} OR {mv_via_template})"
    rows += [
        ("material_versions", "p_mv_insert", "INSERT", "guguta_api", None, "created_by = guguta_actor()"),
        ("material_versions", "p_mv_select", "SELECT", "guguta_api", mv_read, None),
        ("material_versions", "p_mv_w_insert", "INSERT", "guguta_worker", None, "created_by = guguta_actor()"),
        ("material_versions", "p_mv_w_select", "SELECT", "guguta_worker", mv_read, None),
    ]
    # artifacts / chunks / embeddings — worker writes under actor context
    rows += [
        ("processing_artifacts", "p_pa_select", "SELECT", "guguta_api", artifact_via_notebook, None),
        ("processing_artifacts", "p_pa_w_all", "ALL", "guguta_worker", artifact_via_notebook, artifact_via_notebook),
        ("chunks", "p_chunk_select", "SELECT", "guguta_api", chunk_via_notebook, None),
        ("chunks", "p_chunk_w_all", "ALL", "guguta_worker", chunk_via_notebook, chunk_via_notebook),
        ("embeddings", "p_emb_select", "SELECT", "guguta_api", emb_via_notebook, None),
        ("embeddings", "p_emb_w_all", "ALL", "guguta_worker", emb_via_notebook, emb_via_notebook),
    ]
    # embedding_spaces — readable config; writes via admin service (role-checked)
    rows += [
        ("embedding_spaces", "p_es_read", "SELECT", "guguta_api", "true", None),
        ("embedding_spaces", "p_es_w_all", "ALL", "guguta_api", "true", "true"),
        ("embedding_spaces", "p_es_worker_read", "SELECT", "guguta_worker", "true", None),
    ]
    # processing_jobs — api: own; worker: the queue
    rows += [
        ("processing_jobs", "p_job_actor", "ALL", "guguta_api", "actor_id = guguta_actor()", "actor_id = guguta_actor()"),
        ("processing_jobs", "p_job_queue", "ALL", "guguta_worker", "true", "true"),
    ]
    # share tables
    rows += [
        ("share_snapshots", "p_ss_author", "ALL", "guguta_api", "author_id = guguta_actor()", "author_id = guguta_actor()"),
        ("share_snapshots", "p_ss_recipient_read", "SELECT", "guguta_api", ss_read, None),
        ("share_materials", "p_sm_author", "ALL", "guguta_api", ss_via_author.format(col="snapshot_id"), ss_via_author.format(col="snapshot_id")),
        ("share_materials", "p_sm_recipient_read", "SELECT", "guguta_api", ss_via_author.format(col="snapshot_id").replace("ss.author_id = guguta_actor()", "(ss.author_id = guguta_actor() OR (ss.status = 'active' AND ss.id = guguta_share_context()))"), None),
        ("share_credentials", "p_sc_author", "ALL", "guguta_api", ss_via_author.format(col="snapshot_id"), ss_via_author.format(col="snapshot_id")),
        ("share_imports", "p_si_recipient", "ALL", "guguta_api", "recipient_id = guguta_actor()", "recipient_id = guguta_actor()"),
    ]
    # idempotency
    rows += [
        ("idempotency_records", "p_idem_self", "ALL", "guguta_api", "actor_id = guguta_actor()", "actor_id = guguta_actor()"),
    ]
    # catalog
    rows += [
        ("templates", "p_t_read", "SELECT", "guguta_api", tv_read, None),
        ("templates", "p_t_author", "ALL", "guguta_api", "created_by = guguta_actor()", "created_by = guguta_actor()"),
        ("template_versions", "p_tv_read", "SELECT", "guguta_api", tv_read, None),
        ("template_versions", "p_tv_author", "ALL", "guguta_api", "created_by = guguta_actor()", "created_by = guguta_actor()"),
        ("template_materials", "p_tm_read", "SELECT", "guguta_api", tv_via_template_read, None),
        ("template_materials", "p_tm_insert", "INSERT", "guguta_api", None, tv_via_template_read),
        ("template_materials", "p_tm_update", "UPDATE", "guguta_api", tv_via_template_read, tv_via_template_read),
        ("template_materials", "p_tm_delete", "DELETE", "guguta_api", tv_via_template_read, None),
    ]
    # audit / outbox
    rows += [
        ("audit_events", "p_audit_insert_api", "INSERT", "guguta_api", None, "true"),
        ("audit_events", "p_audit_insert_worker", "INSERT", "guguta_worker", None, "true"),
        ("audit_events", "p_audit_read", "SELECT", "guguta_api", "current_setting('app.audit_access', true) = 'granted'", None),
        ("outbox_events", "p_outbox_api_insert", "INSERT", "guguta_api", None, "true"),
        ("outbox_events", "p_outbox_worker", "ALL", "guguta_worker", "true", "true"),
    ]
    return rows


_RLS_TABLES = [
    "users", "identities", "sessions", "digital_notebooks", "notebook_sources",
    "notes", "chat_sessions", "chat_messages", "citations", "source_assets",
    "material_versions", "processing_artifacts", "chunks", "embeddings",
    "embedding_spaces", "processing_jobs", "share_snapshots", "share_materials",
    "share_credentials", "share_imports", "idempotency_records", "templates",
    "template_versions", "template_materials", "audit_events", "outbox_events",
]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(_ROLES_SQL)

    # Tables from the models (single source of truth for the initial schema).
    GugutaBase.metadata.create_all(bind=bind)

    # Extra FK once share_snapshots exists.
    op.create_foreign_key(
        "fk_notebooks_origin_snapshot",
        "digital_notebooks",
        "share_snapshots",
        ["origin_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    for stmt in _FUNCTIONS_SQL:
        op.execute(stmt)
    for stmt in _TRIGGERS_SQL:
        op.execute(stmt)

    # RLS: enabled for runtime roles (non-owners); NOT forced so the migrator
    # owner can always run data migrations (documented in ADR-0007).
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

    for table, name, command, role, using, with_check in _policies():
        parts = [f"CREATE POLICY {name} ON {table}"]
        parts.append(f"FOR {command}")
        parts.append(f"TO {role}")
        if using:
            parts.append(f"USING ({using})")
        if with_check:
            parts.append(f"WITH CHECK ({with_check})")
        op.execute(" ".join(parts) + ";")

    # Runtime grants; default privileges cover future tables created by the
    # migrator role (compose bootstrap runs migrations as that role).
    op.execute(
        "GRANT USAGE ON SCHEMA public TO guguta_api, guguta_worker;"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "TO guguta_api, guguta_worker;"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public "
        "TO guguta_api, guguta_worker;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO guguta_api, guguta_worker;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO guguta_api, guguta_worker;"
    )


def downgrade() -> None:
    # Development/test downgrade only: destroys all Guguță data (no prod use —
    # rollback for releases never runs destructive downgrades, R17).
    bind = op.get_bind()
    bind.exec_driver_sql("DROP SCHEMA public CASCADE;")
    bind.exec_driver_sql("CREATE SCHEMA public;")
