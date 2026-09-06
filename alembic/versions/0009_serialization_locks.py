"""F12: transactional serialization locks for import↔revoke and
instantiate↔retire (audit F12).

The recipient/importer cannot FOR UPDATE a row they do not own through RLS,
so the lock is taken via a SECURITY DEFINER function that locks the row and
returns its status. The lock is held until the caller's transaction commits —
giving true serialization between the final status check and the commit.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = """
CREATE OR REPLACE FUNCTION guguta_share_lock(p_snapshot_id uuid)
RETURNS varchar
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT status FROM share_snapshots WHERE id = p_snapshot_id FOR UPDATE;
$$;

CREATE OR REPLACE FUNCTION guguta_template_lock(p_template_id uuid)
RETURNS varchar
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT status FROM templates WHERE id = p_template_id FOR UPDATE;
$$;

GRANT EXECUTE ON FUNCTION guguta_share_lock(uuid) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_template_lock(uuid) TO guguta_api;
"""

_DOWNGRADE = """
REVOKE EXECUTE ON FUNCTION guguta_share_lock(uuid) FROM guguta_api;
REVOKE EXECUTE ON FUNCTION guguta_template_lock(uuid) FROM guguta_api;
DROP FUNCTION IF EXISTS guguta_template_lock(uuid);
DROP FUNCTION IF EXISTS guguta_share_lock(uuid);
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
