"""Keep the partner quiz token even when account sign-in fails.

Revision ID: 0025
Revises: 0024
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE playquiz_exports ADD COLUMN play_token varchar(100);
ALTER TABLE playquiz_exports ALTER COLUMN playquiz_account_id DROP NOT NULL;
ALTER TABLE playquiz_exports ALTER COLUMN playquiz_quiz_id DROP NOT NULL;
""")


def downgrade() -> None:
    # Preserve exported links for rollback; the old contract cannot use tokens.
    op.execute("""
UPDATE playquiz_exports SET playquiz_account_id=COALESCE(playquiz_account_id,''),
 playquiz_quiz_id=COALESCE(playquiz_quiz_id,play_token,'');
ALTER TABLE playquiz_exports ALTER COLUMN playquiz_account_id SET NOT NULL;
ALTER TABLE playquiz_exports ALTER COLUMN playquiz_quiz_id SET NOT NULL;
ALTER TABLE playquiz_exports DROP COLUMN play_token;
""")
