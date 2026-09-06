"""Migration-from-zero and integrity tests against real PostgreSQL (L1)."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.usefixtures("guguta_db")

EXPECTED_TABLES = [
    "users", "identities", "sessions", "digital_notebooks", "source_assets",
    "material_versions", "notebook_sources", "embedding_spaces",
    "processing_artifacts", "chunks", "embeddings", "templates",
    "template_versions", "template_materials", "share_snapshots",
    "share_materials", "share_credentials", "share_imports",
    "idempotency_records", "chat_sessions", "chat_messages", "citations",
    "notes", "processing_jobs", "outbox_events", "audit_events",
]

RLS_TABLES = EXPECTED_TABLES  # every GuguÈ›Äƒ table carries RLS


def test_migrations_from_zero(migrator_engine: sa.Engine) -> None:
    with migrator_engine.connect() as conn:
        version = conn.execute(
            sa.text("SELECT version_num FROM guguta_alembic")
        ).scalar()
        assert version == "0001"
        tables = {
            row[0]
            for row in conn.execute(
                sa.text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            )
        }
        missing = set(EXPECTED_TABLES) - tables
        assert not missing, f"missing tables: {missing}"


def test_rls_enabled(migrator_engine: sa.Engine) -> None:
    with migrator_engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT relname, relrowsecurity FROM pg_class "
                "JOIN pg_namespace ns ON ns.oid = relnamespace "
                "WHERE nspname = 'public' AND relkind = 'r'"
            )
        ).fetchall()
        rls = {name: flag for name, flag in rows}
        for table in RLS_TABLES:
            assert rls.get(table) is True, f"RLS not enabled on {table}"


def test_runtime_roles_not_owners(migrator_engine: sa.Engine) -> None:
    """Runtime roles must not own schema objects (ADR-0007)."""
    with migrator_engine.connect() as conn:
        owners = {
            row[0]
            for row in conn.execute(
                sa.text(
                    "SELECT tableowner FROM pg_tables WHERE schemaname = 'public'"
                )
            )
        }
        assert "guguta_api" not in owners
        assert "guguta_worker" not in owners


def test_embedding_dimension_trigger(migrator_engine: sa.Engine) -> None:
    space_id = uuid.uuid4()
    with migrator_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO embedding_spaces (id, model_name, model_revision, dimension, is_active) "
                "VALUES (:id, 'test-model', 'rev1', 4, true)"
            ),
            {"id": space_id},
        )
        chunk_id = uuid.uuid4()
        artifact_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        user_id = uuid.uuid4()
        mv_id = uuid.uuid4()
        conn.execute(
            sa.text("INSERT INTO users (id, display_name) VALUES (:id, 't')"),
            {"id": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO source_assets (id, kind, mime_type, byte_size, sha256, text_content, created_by) "
                "VALUES (:id, 'text', 'text/plain', 0, :sha, 'hello', :user)"
            ),
            {"id": asset_id, "sha": "0" * 64, "user": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO material_versions (id, source_asset_id, title, created_by) "
                "VALUES (:id, :asset, 'v', :user)"
            ),
            {"id": mv_id, "asset": asset_id, "user": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO processing_artifacts (id, material_version_id, parser, parser_version, chunker, chunker_version) "
                "VALUES (:id, :mv, 'p', '1', 'c', '1')"
            ),
            {"id": artifact_id, "mv": mv_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO chunks (id, artifact_id, position, text) "
                "VALUES (:id, :artifact, 0, 'text')"
            ),
            {"id": chunk_id, "artifact": artifact_id},
        )
        # Wrong dimension (3 vs 4) must be rejected; the savepoint keeps the
        # outer transaction usable after the expected failure.
        with pytest.raises(Exception, match="dimension"):
            nested = conn.begin_nested()
            try:
                conn.execute(
                    sa.text("INSERT INTO embeddings (id, chunk_id, embedding_space_id, embedding) VALUES (:id, :c, :s, :v)"),
                    {"id": uuid.uuid4(), "c": chunk_id, "s": space_id, "v": "[1,2,3]"},
                )
            finally:
                nested.rollback()
        # Correct dimension accepted.
        conn.execute(
            sa.text("INSERT INTO embeddings (id, chunk_id, embedding_space_id, embedding) VALUES (:id, :c, :s, :v)"),
            {"id": uuid.uuid4(), "c": chunk_id, "s": space_id, "v": "[1,2,3,4]"},
        )


def test_published_template_version_immutable(migrator_engine: sa.Engine) -> None:
    template_id = uuid.uuid4()
    version_id = uuid.uuid4()
    author = uuid.uuid4()
    with migrator_engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, display_name) VALUES (:id, 'ed')"),
            {"id": author},
        )
        conn.execute(
            sa.text(
                "INSERT INTO templates (id, slug, title, created_by) VALUES (:id, 'tpl', 'T', :by)"
            ),
            {"id": template_id, "by": author},
        )
        conn.execute(
            sa.text(
                "INSERT INTO template_versions (id, template_id, version, manifest, status, created_by) "
                "VALUES (:id, :t, 1, CAST(:m AS jsonb), 'published', :by)"
            ),
            {"id": version_id, "t": template_id, "m": "{}", "by": author},
        )
        with pytest.raises(Exception, match="immutable"):
            conn.execute(
                sa.text("UPDATE template_versions SET manifest = CAST(:m AS jsonb) WHERE id = :id"),
                {"m": '{"changed": true}', "id": version_id},
            )


def test_material_version_rebind_locked(migrator_engine: sa.Engine) -> None:
    user_id = uuid.uuid4()
    asset_a = uuid.uuid4()
    asset_b = uuid.uuid4()
    mv = uuid.uuid4()
    with migrator_engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, display_name) VALUES (:id, 'u')"),
            {"id": user_id},
        )
        for asset in (asset_a, asset_b):
            conn.execute(
                sa.text(
                    "INSERT INTO source_assets (id, kind, mime_type, byte_size, sha256, text_content, created_by) "
                    "VALUES (:id, 'text', 'text/plain', 0, :sha, 'x', :user)"
                ),
                {"id": asset, "sha": uuid.uuid4().hex, "user": user_id},
            )
        conn.execute(
            sa.text(
                "INSERT INTO material_versions (id, source_asset_id, title, created_by) "
                "VALUES (:id, :asset, 'v', :user)"
            ),
            {"id": mv, "asset": asset_a, "user": user_id},
        )
        with pytest.raises(Exception, match="rebind"):
            conn.execute(
                sa.text("UPDATE material_versions SET source_asset_id = :b WHERE id = :id"),
                {"b": asset_b, "id": mv},
            )


def test_notebook_source_position_unique(migrator_engine: sa.Engine) -> None:
    user_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    mv_id = uuid.uuid4()
    nb_id = uuid.uuid4()
    with migrator_engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO users (id, display_name) VALUES (:id, 'u')"),
            {"id": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO digital_notebooks (id, owner_id, title) VALUES (:id, :o, 'N')"
            ),
            {"id": nb_id, "o": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO source_assets (id, kind, mime_type, byte_size, sha256, text_content, created_by) "
                "VALUES (:id, 'text', 'text/plain', 0, :sha, 'x', :user)"
            ),
            {"id": asset_id, "sha": uuid.uuid4().hex, "user": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO material_versions (id, source_asset_id, title, created_by) "
                "VALUES (:id, :asset, 'v', :user)"
            ),
            {"id": mv_id, "asset": asset_id, "user": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO notebook_sources (id, notebook_id, material_version_id, local_name, position, added_by) "
                "VALUES (:id, :nb, :mv, 's', 0, :user)"
            ),
            {"id": uuid.uuid4(), "nb": nb_id, "mv": mv_id, "user": user_id},
        )
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO notebook_sources (id, notebook_id, material_version_id, local_name, position, added_by) "
                    "VALUES (:id, :nb, :mv, 'dup', 0, :user)"
                ),
                {"id": uuid.uuid4(), "nb": nb_id, "mv": mv_id, "user": user_id},
            )


def test_users_roles_constraint(migrator_engine: sa.Engine) -> None:
    with migrator_engine.begin() as conn:
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, display_name, roles) "
                    "VALUES (:id, 'bad', ARRAY['superadmin'])"
                ),
                {"id": uuid.uuid4()},
            )
