"""Profil școlar (școală, clasă) și consimțăminte (confidențialitate, părinte).

Revision ID: 0024
Revises: 0023
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE users ADD COLUMN IF NOT EXISTS school varchar(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS class_level varchar(10);
ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_class_level;
ALTER TABLE users ADD CONSTRAINT ck_users_class_level CHECK (
 class_level IS NULL OR class_level IN ('I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII')
);

CREATE TABLE IF NOT EXISTS user_consents (
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind varchar(40) NOT NULL,
 version varchar(40) NOT NULL,
 accepted_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (user_id, kind),
 CONSTRAINT ck_user_consents_kind CHECK (kind IN ('privacy','terms','parent'))
);
ALTER TABLE user_consents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_user_consents_self ON user_consents;
CREATE POLICY p_user_consents_self ON user_consents FOR ALL TO guguta_api
 USING (user_id=guguta_actor()) WITH CHECK (user_id=guguta_actor());
GRANT SELECT,INSERT,UPDATE,DELETE ON user_consents TO guguta_api;
""")


def downgrade() -> None:
    op.execute("""
DROP TABLE IF EXISTS user_consents;
ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_class_level;
ALTER TABLE users DROP COLUMN IF EXISTS class_level;
ALTER TABLE users DROP COLUMN IF EXISTS school;
""")
