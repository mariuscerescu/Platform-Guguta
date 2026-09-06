"""Admin credentials storage (encrypted at rest) + content reports helper.

- admin_credentials: provider secrets encrypted with Fernet; the plaintext
  never reaches the DB. RLS denies api/worker directly — access goes through
  SECURITY DEFINER functions that verify the caller's admin role inside the
  database (guguta_admin_assert).
- Decryption for provider use (guguta_credential_decrypt) requires an active
  actor and writes an audit event; set/rotate also write audit events.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = """
CREATE TABLE IF NOT EXISTS admin_credentials (
    id uuid PRIMARY KEY,
    provider varchar(100) NOT NULL,
    name varchar(200) NOT NULL,
    key_id varchar(64) NOT NULL,
    encrypted_payload text NOT NULL,
    created_by uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    rotated_at timestamptz,
    UNIQUE (provider, name)
);
ALTER TABLE admin_credentials ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION guguta_admin_assert(p_actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_roles varchar[]; v_status text;
BEGIN
    IF p_actor IS NULL THEN
        RAISE EXCEPTION 'actor lipsă';
    END IF;
    SELECT roles, status INTO v_roles, v_status FROM users WHERE id = p_actor;
    IF NOT FOUND OR v_status <> 'active' OR NOT ('admin' = ANY (v_roles)) THEN
        RAISE EXCEPTION 'rol de administrator necesar';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION guguta_admin_set_credential(
    p_actor uuid, p_provider text, p_name text, p_key_id text, p_payload text
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid;
BEGIN
    PERFORM guguta_admin_assert(p_actor);
    SELECT id INTO v_id FROM admin_credentials
    WHERE provider = p_provider AND name = p_name;
    IF v_id IS NULL THEN
        INSERT INTO admin_credentials (id, provider, name, key_id, encrypted_payload, created_by)
        VALUES (gen_random_uuid(), p_provider, p_name, p_key_id, p_payload, p_actor)
        RETURNING id INTO v_id;
        INSERT INTO audit_events (id, actor_id, action, target_type, target_id, result)
        VALUES (gen_random_uuid(), p_actor, 'credential_set', 'admin_credential', v_id, 'allowed');
    ELSE
        UPDATE admin_credentials SET key_id = p_key_id, encrypted_payload = p_payload,
               rotated_at = now() WHERE id = v_id;
        INSERT INTO audit_events (id, actor_id, action, target_type, target_id, result)
        VALUES (gen_random_uuid(), p_actor, 'credential_update', 'admin_credential', v_id, 'allowed');
    END IF;
    RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION guguta_admin_list_credentials(p_actor uuid)
RETURNS TABLE(id uuid, provider varchar, name varchar, key_id varchar,
              created_at timestamptz, rotated_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT guguta_admin_assert(p_actor);
    SELECT c.id, c.provider, c.name, c.key_id, c.created_at, c.rotated_at
    FROM admin_credentials c ORDER BY c.provider, c.name;
$$;

CREATE OR REPLACE FUNCTION guguta_admin_delete_credential(p_actor uuid, p_id uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    PERFORM guguta_admin_assert(p_actor);
    DELETE FROM admin_credentials WHERE id = p_id;
    INSERT INTO audit_events (id, actor_id, action, target_type, target_id, result)
    VALUES (gen_random_uuid(), p_actor, 'credential_delete', 'admin_credential', p_id, 'allowed');
END $$;

CREATE OR REPLACE FUNCTION guguta_admin_get_credential(p_actor uuid, p_id uuid)
RETURNS TABLE(provider varchar, name varchar, key_id varchar, encrypted_payload text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    PERFORM guguta_admin_assert(p_actor);
    RETURN QUERY SELECT c.provider, c.name, c.key_id, c.encrypted_payload
    FROM admin_credentials c WHERE c.id = p_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'credențial inexistent';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION guguta_credential_decrypt(p_actor uuid, p_provider text, p_name text)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_payload text; v_status text;
BEGIN
    IF p_actor IS NULL THEN RAISE EXCEPTION 'actor lipsă'; END IF;
    SELECT status INTO v_status FROM users WHERE id = p_actor;
    IF v_status IS NULL OR v_status <> 'active' THEN
        RAISE EXCEPTION 'actor inactiv';
    END IF;
    SELECT encrypted_payload INTO v_payload FROM admin_credentials
    WHERE provider = p_provider AND name = p_name;
    IF v_payload IS NULL THEN
        RAISE EXCEPTION 'credențial inexistent';
    END IF;
    INSERT INTO audit_events (id, actor_id, action, target_type, target_id, result)
    VALUES (gen_random_uuid(), p_actor, 'credential_decrypt', 'admin_credential',
            (SELECT id FROM admin_credentials WHERE provider = p_provider AND name = p_name),
            'allowed');
    RETURN v_payload;
END $$;
"""

_DOWNGRADE = """
DROP FUNCTION IF EXISTS guguta_credential_decrypt(uuid, text, text);
DROP FUNCTION IF EXISTS guguta_admin_get_credential(uuid, uuid);
DROP FUNCTION IF EXISTS guguta_admin_delete_credential(uuid, uuid);
DROP FUNCTION IF EXISTS guguta_admin_list_credentials(uuid);
DROP FUNCTION IF EXISTS guguta_admin_set_credential(uuid, text, text, text, text);
DROP FUNCTION IF EXISTS guguta_admin_assert(uuid);
DROP TABLE IF EXISTS admin_credentials;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
