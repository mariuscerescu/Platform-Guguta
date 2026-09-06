"""Share snapshots may outlive the author's notebook (L7).

Deleting a notebook revokes its active shares first; the snapshot row stays
as the historical record, so notebook_id becomes nullable with ON DELETE
SET NULL (A10/A28 — recipient copies are unaffected either way).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = """
ALTER TABLE share_snapshots ALTER COLUMN notebook_id DROP NOT NULL;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'share_snapshots_notebook_id_fkey'
               AND conrelid = 'share_snapshots'::regclass) THEN
        ALTER TABLE share_snapshots DROP CONSTRAINT share_snapshots_notebook_id_fkey;
    END IF;
    ALTER TABLE share_snapshots ADD CONSTRAINT share_snapshots_notebook_id_fkey
        FOREIGN KEY (notebook_id) REFERENCES digital_notebooks(id) ON DELETE SET NULL;
END $$;
"""

_DOWNGRADE = """
UPDATE share_snapshots SET notebook_id = NULL WHERE notebook_id IS NULL;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'share_snapshots_notebook_id_fkey'
               AND conrelid = 'share_snapshots'::regclass) THEN
        ALTER TABLE share_snapshots DROP CONSTRAINT share_snapshots_notebook_id_fkey;
    END IF;
    ALTER TABLE share_snapshots ADD CONSTRAINT share_snapshots_notebook_id_fkey
        FOREIGN KEY (notebook_id) REFERENCES digital_notebooks(id) ON DELETE RESTRICT;
END $$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
