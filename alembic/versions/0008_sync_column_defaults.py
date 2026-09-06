"""Sync DB-level defaults with the current models (L8 alignment).

Older databases were migrated from images built before the server_default
synchronization (e.g. identities.email_verified), which made raw INSERTs —
guguta_provision_user, worker paths — fail with NotNullViolation. This
migration re-applies every column default idempotently (SET DEFAULT is a
no-op when equal). The list is GENERATED from the current models.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULTS = """
ALTER TABLE embedding_spaces ALTER COLUMN distance_strategy SET DEFAULT 'cosine';
ALTER TABLE embedding_spaces ALTER COLUMN is_active SET DEFAULT 'false';
ALTER TABLE embedding_spaces ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE outbox_events ALTER COLUMN payload SET DEFAULT '{}';
ALTER TABLE outbox_events ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE users ALTER COLUMN status SET DEFAULT 'active';
ALTER TABLE users ALTER COLUMN roles SET DEFAULT '{user}';
ALTER TABLE users ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE users ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE audit_events ALTER COLUMN result SET DEFAULT 'allowed';
ALTER TABLE audit_events ALTER COLUMN details SET DEFAULT '{}';
ALTER TABLE audit_events ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE idempotency_records ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE identities ALTER COLUMN email_verified SET DEFAULT 'false';
ALTER TABLE identities ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE processing_jobs ALTER COLUMN target_revision SET DEFAULT '1';
ALTER TABLE processing_jobs ALTER COLUMN payload SET DEFAULT '{}';
ALTER TABLE processing_jobs ALTER COLUMN status SET DEFAULT 'queued';
ALTER TABLE processing_jobs ALTER COLUMN attempts SET DEFAULT '0';
ALTER TABLE processing_jobs ALTER COLUMN max_attempts SET DEFAULT '5';
ALTER TABLE processing_jobs ALTER COLUMN run_after SET DEFAULT 'now()';
ALTER TABLE processing_jobs ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE processing_jobs ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE sessions ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE source_assets ALTER COLUMN byte_size SET DEFAULT '0';
ALTER TABLE source_assets ALTER COLUMN retention_status SET DEFAULT 'retained';
ALTER TABLE source_assets ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE templates ALTER COLUMN language SET DEFAULT 'ro';
ALTER TABLE templates ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE templates ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE templates ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE material_versions ALTER COLUMN version SET DEFAULT '1';
ALTER TABLE material_versions ALTER COLUMN provenance SET DEFAULT '{}';
ALTER TABLE material_versions ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE template_versions ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE template_versions ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE digital_notebooks ALTER COLUMN status SET DEFAULT 'active';
ALTER TABLE digital_notebooks ALTER COLUMN origin SET DEFAULT 'personal';
ALTER TABLE digital_notebooks ALTER COLUMN context_revision SET DEFAULT '1';
ALTER TABLE digital_notebooks ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE digital_notebooks ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE notebook_sources ALTER COLUMN selected_for_chat SET DEFAULT 'true';
ALTER TABLE notebook_sources ALTER COLUMN status SET DEFAULT 'uploading';
ALTER TABLE notebook_sources ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE notebook_sources ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE processing_artifacts ALTER COLUMN status SET DEFAULT 'running';
ALTER TABLE processing_artifacts ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE chat_sessions ALTER COLUMN created_revision SET DEFAULT '1';
ALTER TABLE chat_sessions ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE chat_sessions ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE chat_messages ALTER COLUMN status SET DEFAULT 'complete';
ALTER TABLE chat_messages ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE citations ALTER COLUMN locator SET DEFAULT '{}';
ALTER TABLE citations ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE notes ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE notes ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE share_snapshots ALTER COLUMN status SET DEFAULT 'active';
ALTER TABLE share_snapshots ALTER COLUMN schema_version SET DEFAULT '1';
ALTER TABLE share_snapshots ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE share_imports ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE idempotency_records ALTER COLUMN created_at SET DEFAULT 'now()';
ALTER TABLE templates ALTER COLUMN updated_at SET DEFAULT 'now()';
ALTER TABLE processing_jobs ALTER COLUMN updated_at SET DEFAULT 'now()';
"""


def upgrade() -> None:
    op.execute(_DEFAULTS)


def downgrade() -> None:
    # Defaults are metadata; intentional no-op on downgrade.
    pass
