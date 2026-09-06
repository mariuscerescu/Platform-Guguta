"""Chat message ordering: seq is per-session, not globally unique.

0001 created chat_messages.seq with a global UNIQUE (model drift); the
ordering contract is per-session. This migration replaces the global
constraint with UNIQUE (session_id, seq) and a lookup index.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_messages_seq_key'
                       AND conrelid = 'chat_messages'::regclass) THEN
                ALTER TABLE chat_messages DROP CONSTRAINT chat_messages_seq_key;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ux_chat_messages_session_seq'
                           AND conrelid = 'chat_messages'::regclass) THEN
                ALTER TABLE chat_messages
                    ADD CONSTRAINT ux_chat_messages_session_seq UNIQUE (session_id, seq);
            END IF;
        END $$;
        CREATE INDEX IF NOT EXISTS ix_chat_messages_session_seq
            ON chat_messages (session_id, seq);
        """
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_seq", table_name="chat_messages")
    op.drop_constraint("ux_chat_messages_session_seq", "chat_messages", type_="unique")
