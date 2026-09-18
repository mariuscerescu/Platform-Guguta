"""Add source-grounded quizzes and attempts.

Revision ID: 0017
Revises: 0016
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS quizzes (
 id uuid PRIMARY KEY, notebook_id uuid NOT NULL REFERENCES digital_notebooks(id) ON DELETE CASCADE,
 created_by uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 quantity varchar(20) NOT NULL DEFAULT 'standard', difficulty varchar(20) NOT NULL DEFAULT 'medium',
 question_types jsonb NOT NULL, instructions text, selected_source_ids jsonb NOT NULL,
 language varchar(20) NOT NULL DEFAULT 'ro', status varchar(24) NOT NULL DEFAULT 'queued',
 title varchar(500), model_name varchar(500), prompt_version varchar(100), error_detail text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 CONSTRAINT ck_quizzes_quantity CHECK (quantity IN ('fewer','standard','more')),
 CONSTRAINT ck_quizzes_difficulty CHECK (difficulty IN ('easy','medium','hard')),
 CONSTRAINT ck_quizzes_status CHECK (status IN ('queued','generating','ready','failed'))
);
CREATE INDEX IF NOT EXISTS ix_quizzes_notebook_created ON quizzes(notebook_id,created_at DESC);
DROP TRIGGER IF EXISTS trg_quizzes_touch ON quizzes;
CREATE TRIGGER trg_quizzes_touch BEFORE UPDATE ON quizzes FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

CREATE TABLE IF NOT EXISTS quiz_questions (
 id uuid PRIMARY KEY, quiz_id uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
 position integer NOT NULL, question_type varchar(30) NOT NULL, prompt text NOT NULL, hint text NOT NULL DEFAULT '',
 concepts jsonb NOT NULL DEFAULT '[]'::jsonb, options jsonb NOT NULL DEFAULT '[]'::jsonb,
 accepted_answers jsonb NOT NULL DEFAULT '[]'::jsonb, reference_answer text NOT NULL DEFAULT '',
 required_concepts jsonb NOT NULL DEFAULT '[]'::jsonb, optional_concepts jsonb NOT NULL DEFAULT '[]'::jsonb,
 evidence jsonb NOT NULL DEFAULT '[]'::jsonb, version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT ux_quiz_questions_position UNIQUE (quiz_id,position),
 CONSTRAINT ck_quiz_questions_position CHECK (position >= 0),
 CONSTRAINT ck_quiz_questions_version CHECK (version >= 1),
 CONSTRAINT ck_quiz_questions_type CHECK (question_type IN ('multiple_choice','multiple_select','fill_in_blank','short_answer'))
);
CREATE INDEX IF NOT EXISTS ix_quiz_questions_quiz ON quiz_questions(quiz_id,position);
DROP TRIGGER IF EXISTS trg_quiz_questions_touch ON quiz_questions;
CREATE TRIGGER trg_quiz_questions_touch BEFORE UPDATE ON quiz_questions FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

CREATE TABLE IF NOT EXISTS quiz_attempts (
 id uuid PRIMARY KEY, quiz_id uuid NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, current_index integer NOT NULL DEFAULT 0,
 question_order jsonb NOT NULL, answers jsonb NOT NULL DEFAULT '{}'::jsonb,
 started_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 CONSTRAINT ck_quiz_attempts_index CHECK (current_index >= 0)
);
CREATE INDEX IF NOT EXISTS ix_quiz_attempts_quiz_user ON quiz_attempts(quiz_id,user_id,updated_at DESC);
DROP TRIGGER IF EXISTS trg_quiz_attempts_touch ON quiz_attempts;
CREATE TRIGGER trg_quiz_attempts_touch BEFORE UPDATE ON quiz_attempts FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

ALTER TABLE quizzes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_quizzes_api ON quizzes;
CREATE POLICY p_quizzes_api ON quizzes FOR ALL TO guguta_api USING (created_by=guguta_actor())
 WITH CHECK (created_by=guguta_actor() AND EXISTS (SELECT 1 FROM digital_notebooks n WHERE n.id=notebook_id AND n.owner_id=guguta_actor()));
DROP POLICY IF EXISTS p_quizzes_worker ON quizzes;
CREATE POLICY p_quizzes_worker ON quizzes FOR ALL TO guguta_worker USING (created_by=guguta_actor()) WITH CHECK (created_by=guguta_actor());

ALTER TABLE quiz_questions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_quiz_questions_api ON quiz_questions;
CREATE POLICY p_quiz_questions_api ON quiz_questions FOR ALL TO guguta_api
 USING (EXISTS (SELECT 1 FROM quizzes q WHERE q.id=quiz_id AND q.created_by=guguta_actor()))
 WITH CHECK (EXISTS (SELECT 1 FROM quizzes q WHERE q.id=quiz_id AND q.created_by=guguta_actor()));
DROP POLICY IF EXISTS p_quiz_questions_worker ON quiz_questions;
CREATE POLICY p_quiz_questions_worker ON quiz_questions FOR ALL TO guguta_worker
 USING (EXISTS (SELECT 1 FROM quizzes q WHERE q.id=quiz_id AND q.created_by=guguta_actor()))
 WITH CHECK (EXISTS (SELECT 1 FROM quizzes q WHERE q.id=quiz_id AND q.created_by=guguta_actor()));

ALTER TABLE quiz_attempts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_quiz_attempts_api ON quiz_attempts;
CREATE POLICY p_quiz_attempts_api ON quiz_attempts FOR ALL TO guguta_api
 USING (user_id=guguta_actor() AND EXISTS (SELECT 1 FROM quizzes q WHERE q.id=quiz_id AND q.created_by=guguta_actor()))
 WITH CHECK (user_id=guguta_actor() AND EXISTS (SELECT 1 FROM quizzes q WHERE q.id=quiz_id AND q.created_by=guguta_actor()));

GRANT SELECT,INSERT,UPDATE,DELETE ON quizzes TO guguta_api,guguta_worker;
GRANT SELECT,INSERT,UPDATE,DELETE ON quiz_questions TO guguta_api,guguta_worker;
GRANT SELECT,INSERT,UPDATE,DELETE ON quiz_attempts TO guguta_api;
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS quiz_attempts CASCADE")
    op.execute("DROP TABLE IF EXISTS quiz_questions CASCADE")
    op.execute("DROP TABLE IF EXISTS quizzes CASCADE")
