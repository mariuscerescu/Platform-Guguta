"""Add asynchronous single-speaker Audio Overviews.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-18
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS audio_overviews (
    id uuid PRIMARY KEY,
    notebook_id uuid NOT NULL REFERENCES digital_notebooks(id) ON DELETE CASCADE,
    created_by uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    format varchar(32) NOT NULL,
    selected_source_ids jsonb NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'queued',
    title varchar(500),
    script_text text,
    audio_storage_key varchar(1000),
    mime_type varchar(255) NOT NULL DEFAULT 'audio/wav',
    duration_seconds numeric(10,2),
    script_model_name varchar(500),
    tts_model_name varchar(500),
    prompt_version varchar(100),
    error_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT ck_audio_overviews_format CHECK (format IN ('brief','deep_dive')),
    CONSTRAINT ck_audio_overviews_status CHECK (
        status IN ('queued','generating_script','synthesizing','ready','failed')
    )
);
CREATE INDEX IF NOT EXISTS ix_audio_overviews_notebook_created
    ON audio_overviews(notebook_id, created_at);
DROP TRIGGER IF EXISTS trg_audio_overviews_touch ON audio_overviews;
CREATE TRIGGER trg_audio_overviews_touch BEFORE UPDATE ON audio_overviews
    FOR EACH ROW EXECUTE FUNCTION guguta_touch_updated_at();

ALTER TABLE audio_overviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_audio_overviews_api ON audio_overviews;
CREATE POLICY p_audio_overviews_api ON audio_overviews FOR ALL TO guguta_api
    USING (created_by = guguta_actor())
    WITH CHECK (
        created_by = guguta_actor()
        AND EXISTS (
            SELECT 1 FROM digital_notebooks dn
            WHERE dn.id = notebook_id AND dn.owner_id = guguta_actor()
        )
    );
DROP POLICY IF EXISTS p_audio_overviews_worker ON audio_overviews;
CREATE POLICY p_audio_overviews_worker ON audio_overviews FOR ALL TO guguta_worker
    USING (created_by = guguta_actor())
    WITH CHECK (created_by = guguta_actor());

GRANT SELECT, INSERT, UPDATE, DELETE ON audio_overviews TO guguta_api, guguta_worker;
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audio_overviews CASCADE;")
