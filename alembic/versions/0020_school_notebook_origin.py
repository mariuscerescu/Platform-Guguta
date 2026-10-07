"""Classify published source notebooks as school notebooks.

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE digital_notebooks DROP CONSTRAINT ck_notebooks_origin")
    op.execute(
        "ALTER TABLE digital_notebooks ADD CONSTRAINT ck_notebooks_origin "
        "CHECK (origin IN ('personal','empty','template','import','school'))"
    )


def downgrade() -> None:
    op.execute("UPDATE digital_notebooks SET origin = 'personal' WHERE origin = 'school'")
    op.execute("ALTER TABLE digital_notebooks DROP CONSTRAINT ck_notebooks_origin")
    op.execute(
        "ALTER TABLE digital_notebooks ADD CONSTRAINT ck_notebooks_origin "
        "CHECK (origin IN ('personal','empty','template','import'))"
    )
