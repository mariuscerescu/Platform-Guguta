"""PlayQuiz extern (ADR-023): exporturi de quiz și consimțăminte.

Revision ID: 0023
Revises: 0022
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS playquiz_consents (
 user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 consented_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS playquiz_exports (
 quiz_id uuid PRIMARY KEY REFERENCES quizzes(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 playquiz_account_id varchar(100) NOT NULL,
 playquiz_quiz_id varchar(100) NOT NULL,
 play_url text NOT NULL,
 content_hash varchar(80) NOT NULL,
 exported_at timestamptz NOT NULL DEFAULT now(),
 last_handoff_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_playquiz_exports_user ON playquiz_exports(user_id, exported_at DESC);
DROP TRIGGER IF EXISTS trg_playquiz_exports_touch ON playquiz_exports;
CREATE TRIGGER trg_playquiz_exports_touch BEFORE UPDATE ON playquiz_exports FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

ALTER TABLE playquiz_consents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_playquiz_consents_api ON playquiz_consents;
CREATE POLICY p_playquiz_consents_api ON playquiz_consents FOR ALL TO guguta_api
 USING (user_id=guguta_actor()) WITH CHECK (user_id=guguta_actor());

ALTER TABLE playquiz_exports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_playquiz_exports_api ON playquiz_exports;
CREATE POLICY p_playquiz_exports_api ON playquiz_exports FOR ALL TO guguta_api
 USING (user_id=guguta_actor()) WITH CHECK (user_id=guguta_actor());

GRANT SELECT,INSERT,UPDATE,DELETE ON playquiz_consents TO guguta_api;
GRANT SELECT,INSERT,UPDATE,DELETE ON playquiz_exports TO guguta_api;
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS playquiz_exports; DROP TABLE IF EXISTS playquiz_consents;")
