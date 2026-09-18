"""Add source-grounded flashcard decks and study sessions.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-18
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS flashcard_decks (
    id uuid PRIMARY KEY,
    notebook_id uuid NOT NULL REFERENCES digital_notebooks(id) ON DELETE CASCADE,
    created_by uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quantity varchar(20) NOT NULL DEFAULT 'standard',
    difficulty varchar(20) NOT NULL DEFAULT 'medium',
    instructions text,
    selected_source_ids jsonb NOT NULL,
    language varchar(20) NOT NULL DEFAULT 'ro',
    status varchar(24) NOT NULL DEFAULT 'queued',
    title varchar(500),
    model_name varchar(500),
    prompt_version varchar(100),
    error_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT ck_flashcard_decks_quantity CHECK (quantity IN ('fewer','standard','more')),
    CONSTRAINT ck_flashcard_decks_difficulty CHECK (difficulty IN ('easy','medium','hard')),
    CONSTRAINT ck_flashcard_decks_status CHECK (status IN ('queued','generating','ready','failed'))
);
CREATE INDEX IF NOT EXISTS ix_flashcard_decks_notebook_created
    ON flashcard_decks(notebook_id, created_at DESC);
DROP TRIGGER IF EXISTS trg_flashcard_decks_touch ON flashcard_decks;
CREATE TRIGGER trg_flashcard_decks_touch BEFORE UPDATE ON flashcard_decks
    FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

CREATE TABLE IF NOT EXISTS flashcards (
    id uuid PRIMARY KEY,
    deck_id uuid NOT NULL REFERENCES flashcard_decks(id) ON DELETE CASCADE,
    position integer NOT NULL,
    front text NOT NULL,
    back text NOT NULL,
    concept varchar(500),
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_flashcards_deck_position UNIQUE (deck_id, position),
    CONSTRAINT ck_flashcards_position CHECK (position >= 0)
);
CREATE INDEX IF NOT EXISTS ix_flashcards_deck ON flashcards(deck_id, position);

CREATE TABLE IF NOT EXISTS flashcard_sessions (
    id uuid PRIMARY KEY,
    deck_id uuid NOT NULL REFERENCES flashcard_decks(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode varchar(20) NOT NULL DEFAULT 'all',
    card_order jsonb NOT NULL,
    current_index integer NOT NULL DEFAULT 0,
    results jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT ck_flashcard_sessions_mode CHECK (mode IN ('all','same','missed')),
    CONSTRAINT ck_flashcard_sessions_index CHECK (current_index >= 0)
);
CREATE INDEX IF NOT EXISTS ix_flashcard_sessions_deck_user
    ON flashcard_sessions(deck_id, user_id, updated_at DESC);
DROP TRIGGER IF EXISTS trg_flashcard_sessions_touch ON flashcard_sessions;
CREATE TRIGGER trg_flashcard_sessions_touch BEFORE UPDATE ON flashcard_sessions
    FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

ALTER TABLE flashcard_decks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_flashcard_decks_api ON flashcard_decks;
CREATE POLICY p_flashcard_decks_api ON flashcard_decks FOR ALL TO guguta_api
    USING (created_by = guguta_actor())
    WITH CHECK (
        created_by = guguta_actor() AND EXISTS (
            SELECT 1 FROM digital_notebooks dn
            WHERE dn.id = notebook_id AND dn.owner_id = guguta_actor()
        )
    );
DROP POLICY IF EXISTS p_flashcard_decks_worker ON flashcard_decks;
CREATE POLICY p_flashcard_decks_worker ON flashcard_decks FOR ALL TO guguta_worker
    USING (created_by = guguta_actor()) WITH CHECK (created_by = guguta_actor());

ALTER TABLE flashcards ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_flashcards_api ON flashcards;
CREATE POLICY p_flashcards_api ON flashcards FOR ALL TO guguta_api
    USING (EXISTS (SELECT 1 FROM flashcard_decks d WHERE d.id = deck_id AND d.created_by = guguta_actor()))
    WITH CHECK (EXISTS (SELECT 1 FROM flashcard_decks d WHERE d.id = deck_id AND d.created_by = guguta_actor()));
DROP POLICY IF EXISTS p_flashcards_worker ON flashcards;
CREATE POLICY p_flashcards_worker ON flashcards FOR ALL TO guguta_worker
    USING (EXISTS (SELECT 1 FROM flashcard_decks d WHERE d.id = deck_id AND d.created_by = guguta_actor()))
    WITH CHECK (EXISTS (SELECT 1 FROM flashcard_decks d WHERE d.id = deck_id AND d.created_by = guguta_actor()));

ALTER TABLE flashcard_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_flashcard_sessions_api ON flashcard_sessions;
CREATE POLICY p_flashcard_sessions_api ON flashcard_sessions FOR ALL TO guguta_api
    USING (user_id = guguta_actor() AND EXISTS (
        SELECT 1 FROM flashcard_decks d WHERE d.id = deck_id AND d.created_by = guguta_actor()
    ))
    WITH CHECK (user_id = guguta_actor() AND EXISTS (
        SELECT 1 FROM flashcard_decks d WHERE d.id = deck_id AND d.created_by = guguta_actor()
    ));

GRANT SELECT, INSERT, UPDATE, DELETE ON flashcard_decks TO guguta_api, guguta_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON flashcards TO guguta_api, guguta_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON flashcard_sessions TO guguta_api;
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flashcard_sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS flashcards CASCADE;")
    op.execute("DROP TABLE IF EXISTS flashcard_decks CASCADE;")
