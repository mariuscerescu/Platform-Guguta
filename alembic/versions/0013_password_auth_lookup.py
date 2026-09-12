"""Add password authentication lookup function.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-11
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE OR REPLACE FUNCTION guguta_password_auth_lookup(p_email text)
RETURNS TABLE (
    user_id uuid,
    password_hash text,
    display_name text,
    roles varchar(50)[]
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    RETURN QUERY
    SELECT pc.user_id, pc.password_hash, u.display_name::text, u.roles
    FROM password_credentials pc
    JOIN users u ON u.id = pc.user_id
    WHERE pc.email = lower(trim(p_email))
      AND u.status = 'active';
END;
$$;
REVOKE ALL ON FUNCTION guguta_password_auth_lookup(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION guguta_password_auth_lookup(text) TO guguta_api;
"""
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS guguta_password_auth_lookup(text);")
