"""Add password authentication credentials for Guguță MVP.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-11
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UP = """
CREATE TABLE IF NOT EXISTS password_credentials (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_password_credentials_email CHECK (
        email = lower(email) AND position('@' in email) > 1 AND length(email) <= 320
    ),
    CONSTRAINT ck_password_credentials_hash CHECK (length(password_hash) >= 40)
);

CREATE TRIGGER trg_password_credentials_touch
BEFORE UPDATE ON password_credentials
FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

REVOKE ALL ON password_credentials FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON password_credentials TO guguta_api;
"""

_DOWN = """
DROP TRIGGER IF EXISTS trg_password_credentials_touch ON password_credentials;
DROP TABLE IF EXISTS password_credentials;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
