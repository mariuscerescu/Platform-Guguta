"""Chunk offsets + artifact deduplication (GHID §6.3 idempotent publish).

- chunks.char_start / char_end: character offsets inside the extracted unit.
- ux_artifacts_mv_parser: one complete artifact per
  (material_version, parser, parser_version, chunker, chunker_version) —
  a stale worker publishing twice hits a unique violation instead of
  duplicating the index (retry safety).

Idempotent: migration 0001 builds tables from the current models, so on a
fresh database these columns may already exist; on databases migrated from
older builds they are added here.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = """
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS char_start INTEGER;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS char_end INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS ux_artifacts_mv_parser
    ON processing_artifacts (material_version_id, parser, parser_version,
                             chunker, chunker_version)
    WHERE status = 'complete';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public'
                   AND tablename = 'embedding_spaces'
                   AND policyname = 'p_es_worker_write') THEN
        CREATE POLICY p_es_worker_write ON embedding_spaces FOR ALL
            TO guguta_worker USING (true) WITH CHECK (true);
    END IF;
    -- INSERT ... RETURNING needs a SELECT policy for the new row: a freshly
    -- created asset/version has no notebook path yet, so the creator must be
    -- able to read their own rows (content downloads stay service-checked).
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public'
                   AND tablename = 'source_assets'
                   AND policyname = 'p_sa_creator_read') THEN
        CREATE POLICY p_sa_creator_read ON source_assets FOR SELECT
            TO guguta_api USING (created_by = guguta_actor());
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public'
                   AND tablename = 'material_versions'
                   AND policyname = 'p_mv_creator_read') THEN
        CREATE POLICY p_mv_creator_read ON material_versions FOR SELECT
            TO guguta_api USING (created_by = guguta_actor());
    END IF;
END $$;
"""

_DOWNGRADE = """
DROP POLICY IF EXISTS p_mv_creator_read ON material_versions;
DROP POLICY IF EXISTS p_sa_creator_read ON source_assets;
DROP POLICY IF EXISTS p_es_worker_write ON embedding_spaces;
DROP INDEX IF EXISTS ux_artifacts_mv_parser;
ALTER TABLE chunks DROP COLUMN IF EXISTS char_end;
ALTER TABLE chunks DROP COLUMN IF EXISTS char_start;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
