"""Conversation-scoped sources and durable private-file deletion.

Revision ID: 0021
Revises: 0020
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE notebook_sources ADD COLUMN IF NOT EXISTS chat_session_id uuid REFERENCES chat_sessions(id) ON DELETE CASCADE;
ALTER TABLE notebook_sources ADD COLUMN IF NOT EXISTS chat_message_id uuid REFERENCES chat_messages(id) ON DELETE SET NULL;
ALTER TABLE notebook_sources ADD CONSTRAINT ck_attachment_message CHECK (chat_message_id IS NULL OR chat_session_id IS NOT NULL);
CREATE INDEX ix_sources_chat ON notebook_sources(chat_session_id,chat_message_id) WHERE chat_session_id IS NOT NULL;
CREATE TABLE storage_deletions (
    storage_key varchar(1024) PRIMARY KEY,
    created_by uuid NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE storage_deletions ENABLE ROW LEVEL SECURITY;
ALTER TABLE storage_deletions FORCE ROW LEVEL SECURITY;
CREATE POLICY p_storage_deletions_api ON storage_deletions FOR ALL TO guguta_api
    USING (created_by=guguta_actor()) WITH CHECK (created_by=guguta_actor());
CREATE POLICY p_storage_deletions_worker ON storage_deletions FOR ALL TO guguta_worker
    USING (true) WITH CHECK (true);
GRANT SELECT,DELETE ON storage_deletions TO guguta_api;
GRANT SELECT,UPDATE,DELETE ON storage_deletions TO guguta_worker;

CREATE FUNCTION guguta_delete_chat_asset() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE asset uuid; key varchar(1024); owner uuid;
BEGIN
    IF OLD.chat_session_id IS NULL THEN RETURN OLD; END IF;
    IF EXISTS (SELECT 1 FROM notebook_sources WHERE material_version_id=OLD.material_version_id)
       OR EXISTS (SELECT 1 FROM template_materials WHERE material_version_id=OLD.material_version_id)
       OR EXISTS (SELECT 1 FROM share_materials WHERE material_version_id=OLD.material_version_id)
    THEN RETURN OLD; END IF;
    SELECT sa.id,sa.storage_key,sa.created_by INTO asset,key,owner
      FROM source_assets sa JOIN material_versions mv ON mv.source_asset_id=sa.id
      WHERE mv.id=OLD.material_version_id;
    DELETE FROM processing_jobs WHERE target_type='material_version' AND target_id=OLD.material_version_id;
    DELETE FROM material_versions WHERE id=OLD.material_version_id;
    IF asset IS NOT NULL AND NOT EXISTS (SELECT 1 FROM material_versions WHERE source_asset_id=asset) THEN
        IF key IS NOT NULL THEN
            INSERT INTO storage_deletions(storage_key,created_by) VALUES(key,owner) ON CONFLICT DO NOTHING;
        END IF;
        DELETE FROM source_assets WHERE id=asset;
    END IF;
    RETURN OLD;
END $$;
REVOKE ALL ON FUNCTION guguta_delete_chat_asset() FROM PUBLIC;
CREATE TRIGGER tr_delete_chat_asset AFTER DELETE ON notebook_sources
    FOR EACH ROW EXECUTE FUNCTION guguta_delete_chat_asset();
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM notebook_sources WHERE chat_session_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM storage_deletions) THEN
        RAISE EXCEPTION 'Delete chat attachments and drain storage deletions before downgrading';
    END IF;
END $$;
DROP TRIGGER tr_delete_chat_asset ON notebook_sources;
DROP FUNCTION guguta_delete_chat_asset();
ALTER TABLE notebook_sources DROP COLUMN chat_message_id;
ALTER TABLE notebook_sources DROP COLUMN chat_session_id;
DROP TABLE storage_deletions;
""")
