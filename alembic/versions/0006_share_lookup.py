"""Share token lookup for recipients (L7).

Recipients look up a share by token hash WITHOUT owning the snapshot — RLS
correctly denies them, so the lookup runs through this narrow SECURITY
DEFINER function. It returns only what the preview/import flow needs.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = """
-- Tolerant to revocation: a recipient retrying a finished import after the
-- author revoked the package must still reach the replay (R36); the status
-- column lets the service refuse NEW imports.
CREATE OR REPLACE FUNCTION guguta_share_lookup(p_token_hash text)
RETURNS TABLE(snapshot_id uuid, credential_kind varchar, snapshot_status varchar)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT sc.snapshot_id, sc.kind, ss.status
    FROM share_credentials sc
    JOIN share_snapshots ss ON ss.id = sc.snapshot_id
    WHERE sc.token_hash = p_token_hash;
$$;

GRANT EXECUTE ON FUNCTION guguta_share_lookup(text) TO guguta_api, guguta_worker;
"""

_DOWNGRADE = """
DROP FUNCTION IF EXISTS guguta_share_lookup(text);
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
