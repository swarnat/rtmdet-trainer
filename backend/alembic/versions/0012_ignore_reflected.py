"""ignore regions (annotations.type = 'ignore') and reflected flag

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "ignore" is a new value of the existing free-text column annotations.type: no schema change needed for it
    op.add_column("annotations", sa.Column("reflected", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    # ignore regions would become real objects: remove them
    op.execute("DELETE FROM annotations WHERE type = 'ignore'")
    op.drop_column("annotations", "reflected")
