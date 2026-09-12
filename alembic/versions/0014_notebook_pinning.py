"""Add pinned_at to digital_notebooks (fixarea unui carnet sus în listă).

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-12
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
ALTER TABLE digital_notebooks
    ADD COLUMN IF NOT EXISTS pinned_at timestamptz NULL;
"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE digital_notebooks DROP COLUMN IF EXISTS pinned_at;")
