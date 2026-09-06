"""B01: fix timestamps fixed at migration time (audit backend 2026-09-06).

`SET DEFAULT 'now()'` stores a literal, not a function — every row created
after migration 0008 gets the same timestamp. This migration re-applies
`SET DEFAULT now()` (no quotes) for every affected column.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FIX = """
ALTER TABLE embedding_spaces ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE outbox_events ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE users ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE users ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE audit_events ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE idempotency_records ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE identities ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE processing_jobs ALTER COLUMN run_after SET DEFAULT now();
ALTER TABLE processing_jobs ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE processing_jobs ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE sessions ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE source_assets ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE templates ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE templates ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE material_versions ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE template_versions ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE digital_notebooks ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE digital_notebooks ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE notebook_sources ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE notebook_sources ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE processing_artifacts ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE chat_sessions ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE chat_sessions ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE chat_messages ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE citations ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE notes ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE notes ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE share_snapshots ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE share_imports ALTER COLUMN created_at SET DEFAULT now();

-- B02: revoke implicit PUBLIC access to all SECURITY DEFINER functions.
-- Without this, any role (including worker) can call admin/session functions.
REVOKE EXECUTE ON FUNCTION guguta_provision_user(text, text, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_create_session(uuid, text, interval) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_resolve_session(text, interval) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_revoke_session(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_revoke_all_for_user(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_admin_assert(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_admin_set_credential(uuid, text, text, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_admin_list_credentials(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_admin_get_credential(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_admin_delete_credential(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_credential_decrypt(uuid, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_share_lookup(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_share_lock(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guguta_template_lock(uuid) FROM PUBLIC;

-- B02: explicit grants (never PUBLIC) for the roles that need them
GRANT EXECUTE ON FUNCTION guguta_provision_user(text, text, text, text) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_create_session(uuid, text, interval) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_resolve_session(text, interval) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_revoke_session(text) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_revoke_all_for_user(uuid) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_admin_set_credential(uuid, text, text, text, text) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_admin_list_credentials(uuid) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_admin_get_credential(uuid, uuid) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_admin_delete_credential(uuid, uuid) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_credential_decrypt(uuid, text, text) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_share_lock(uuid) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_template_lock(uuid) TO guguta_api;
"""


def upgrade() -> None:
    op.execute(_FIX)


def downgrade() -> None:
    # Intentional no-op: restoring broken defaults would be a regression.
    pass
