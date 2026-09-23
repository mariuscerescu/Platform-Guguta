"""Add optional focus instructions to audio overviews.

Revision ID: 0019
Revises: 0018
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE audio_overviews "
        "ADD COLUMN IF NOT EXISTS instructions text;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE audio_overviews "
        "DROP COLUMN IF EXISTS instructions;"
    )
