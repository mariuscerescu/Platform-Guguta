"""Identity provisioning function (ADR-0003).

`guguta_provision_user` is SECURITY DEFINER because first login has no actor
context yet — RLS correctly denies anonymous INSERTs on users/identities, so
provisioning goes through this narrow, audited interface owned by the
migrator role. Lookup-or-create is keyed on issuer + subject (never email
alone); repeat logins only refresh last_login_at/email.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FN = """
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
BEGIN
    IF p_issuer IS NULL OR length(btrim(p_issuer)) = 0
       OR p_subject IS NULL OR length(btrim(p_subject)) = 0 THEN
        RAISE EXCEPTION 'issuer and subject are required';
    END IF;
    SELECT i.user_id INTO v_user
    FROM identities i
    WHERE i.issuer = p_issuer AND i.subject = p_subject;

    IF v_user IS NULL THEN
        INSERT INTO users (id, display_name, email, status, roles)
        VALUES (
            gen_random_uuid(),
            left(coalesce(nullif(btrim(p_display_name), ''), p_subject), 255),
            p_email,
            'active',
            ARRAY['user']::varchar[]
        )
        RETURNING id INTO v_user;
        INSERT INTO identities (id, user_id, issuer, subject, email)
        VALUES (gen_random_uuid(), v_user, p_issuer, p_subject, p_email);
    ELSE
        UPDATE identities
        SET last_login_at = now(),
            email = coalesce(p_email, email)
        WHERE issuer = p_issuer AND subject = p_subject;
    END IF;
    RETURN v_user;
END $$;

-- Session mechanics run as SECURITY DEFINER because they execute BEFORE an
-- actor context exists (cookie bootstrap). RLS still protects every other
-- access path to sessions.
CREATE OR REPLACE FUNCTION guguta_create_session(
    p_user uuid, p_token_hash text, p_absolute_ttl interval
) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    INSERT INTO sessions (id, user_id, token_hash, expires_at)
    VALUES (gen_random_uuid(), p_user, p_token_hash, now() + p_absolute_ttl);
$$;

CREATE OR REPLACE FUNCTION guguta_resolve_session(
    p_token_hash text,
    p_inactivity interval,
    OUT o_session_id uuid,
    OUT o_user_id uuid,
    OUT o_display_name text,
    OUT o_roles varchar[],
    OUT o_status text
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    SELECT s.id, s.user_id, u.display_name, u.roles, u.status
    INTO o_session_id, o_user_id, o_display_name, o_roles, o_status
    FROM sessions s JOIN users u ON u.id = s.user_id
    WHERE s.token_hash = p_token_hash
      AND s.revoked_at IS NULL
      AND s.expires_at > now()
      AND (s.last_seen_at IS NULL OR s.last_seen_at > now() - p_inactivity);
    IF o_session_id IS NOT NULL THEN
        UPDATE sessions SET last_seen_at = now() WHERE id = o_session_id;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION guguta_revoke_session(p_token_hash text) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    WITH r AS (
        UPDATE sessions SET revoked_at = now()
        WHERE token_hash = p_token_hash AND revoked_at IS NULL
        RETURNING 1
    )
    SELECT count(*) FROM r;
$$;

CREATE OR REPLACE FUNCTION guguta_revoke_all_for_user(p_user uuid) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    WITH r AS (
        UPDATE sessions SET revoked_at = now()
        WHERE user_id = p_user AND revoked_at IS NULL
        RETURNING 1
    )
    SELECT count(*) FROM r;
$$;
"""

_GRANTS = """
GRANT EXECUTE ON FUNCTION guguta_provision_user(text, text, text, text) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_create_session(uuid, text, interval) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_resolve_session(text, interval) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_revoke_session(text) TO guguta_api;
GRANT EXECUTE ON FUNCTION guguta_revoke_all_for_user(uuid) TO guguta_api;
"""


def upgrade() -> None:
    op.execute(_FN)
    op.execute(_GRANTS)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS guguta_revoke_all_for_user(uuid);"
        "DROP FUNCTION IF EXISTS guguta_revoke_session(text);"
        "DROP FUNCTION IF EXISTS guguta_resolve_session(text, interval);"
        "DROP FUNCTION IF EXISTS guguta_create_session(uuid, text, interval);"
        "DROP FUNCTION IF EXISTS guguta_provision_user(text, text, text, text);"
    )
