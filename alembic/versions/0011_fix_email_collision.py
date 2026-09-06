"""B13: handle email collision in guguta_provision_user (audit backend).

Two different OIDC identities (different issuer+subject) with the same email
previously caused UniqueViolation on the partial unique index `ux_users_email`.
The fix: if the email is already taken by a different user, set email to NULL
on the new user (identity is issuer+subject, never email alone — ADR-0003).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FIX = """
CREATE OR REPLACE FUNCTION guguta_provision_user(
    p_issuer text,
    p_subject text,
    p_display_name text,
    p_email text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_user uuid;
    v_safe_email text;
BEGIN
    IF p_issuer IS NULL OR length(btrim(p_issuer)) = 0
       OR p_subject IS NULL OR length(btrim(p_subject)) = 0 THEN
        RAISE EXCEPTION 'issuer and subject are required';
    END IF;
    -- B13: never bind identity to email; if the email is already used by a
    -- different user, set it to NULL on the new user instead of failing.
    v_safe_email := p_email;
    IF v_safe_email IS NOT NULL AND EXISTS (
        SELECT 1 FROM users WHERE email = v_safe_email
    ) THEN
        v_safe_email := NULL;
    END IF;
    SELECT i.user_id INTO v_user
    FROM identities i
    WHERE i.issuer = p_issuer AND i.subject = p_subject;

    IF v_user IS NULL THEN
        INSERT INTO users (id, display_name, email, status, roles)
        VALUES (
            gen_random_uuid(),
            left(coalesce(nullif(btrim(p_display_name), ''), p_subject), 255),
            v_safe_email,
            'active',
            ARRAY['user']::varchar[]
        )
        RETURNING id INTO v_user;
        INSERT INTO identities (id, user_id, issuer, subject, email)
        VALUES (gen_random_uuid(), v_user, p_issuer, p_subject, v_safe_email);
    ELSE
        UPDATE identities
        SET last_login_at = now(),
            email = coalesce(v_safe_email, email)
        WHERE issuer = p_issuer AND subject = p_subject;
    END IF;
    RETURN v_user;
END $$;
"""


def upgrade() -> None:
    op.execute(_FIX)


def downgrade() -> None:
    # Restore the original function (without email collision handling)
    pass
