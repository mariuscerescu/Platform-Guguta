"""Defer historic citation references through nested attachment erasure.

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The attachment trigger deletes material versions inside source deletion.
    # SET NULL actions on several citation FKs can run in different orders;
    # validate the final transaction state, not an intermediate cascade state.
    for name in ("message_id", "notebook_source_id", "material_version_id", "chunk_id"):
        op.execute(
            f"ALTER TABLE citations ALTER CONSTRAINT citations_{name}_fkey DEFERRABLE INITIALLY DEFERRED"
        )


def downgrade() -> None:
    for name in ("message_id", "notebook_source_id", "material_version_id", "chunk_id"):
        op.execute(
            f"ALTER TABLE citations ALTER CONSTRAINT citations_{name}_fkey NOT DEFERRABLE"
        )
