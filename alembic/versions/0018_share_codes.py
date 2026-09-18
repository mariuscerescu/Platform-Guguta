"""Add expiring notebook share codes.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE share_snapshots ADD COLUMN IF NOT EXISTS expires_at timestamptz;

CREATE OR REPLACE FUNCTION guguta_share_lookup(p_token_hash text)
RETURNS TABLE(snapshot_id uuid, credential_kind varchar, snapshot_status varchar)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT sc.snapshot_id, sc.kind,
           CASE WHEN ss.status = 'active' AND ss.expires_at IS NOT NULL
                     AND ss.expires_at <= now() THEN 'expired'::varchar
                ELSE ss.status END
    FROM share_credentials sc
    JOIN share_snapshots ss ON ss.id = sc.snapshot_id
    WHERE sc.token_hash = p_token_hash;
$$;

CREATE OR REPLACE FUNCTION guguta_share_lock(p_snapshot_id uuid)
RETURNS varchar
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT CASE WHEN status = 'active' AND expires_at IS NOT NULL
                     AND expires_at <= now() THEN 'expired'::varchar
                ELSE status END
    FROM share_snapshots WHERE id = p_snapshot_id FOR UPDATE;
$$;
""")


def downgrade() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION guguta_share_lookup(p_token_hash text)
RETURNS TABLE(snapshot_id uuid, credential_kind varchar, snapshot_status varchar)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT sc.snapshot_id, sc.kind, ss.status FROM share_credentials sc
    JOIN share_snapshots ss ON ss.id = sc.snapshot_id WHERE sc.token_hash = p_token_hash;
$$;
CREATE OR REPLACE FUNCTION guguta_share_lock(p_snapshot_id uuid)
RETURNS varchar LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT status FROM share_snapshots WHERE id = p_snapshot_id FOR UPDATE;
$$;
ALTER TABLE share_snapshots DROP COLUMN IF EXISTS expires_at;
""")
