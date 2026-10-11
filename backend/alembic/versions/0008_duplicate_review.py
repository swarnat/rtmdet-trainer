"""duplicate review: difference score and "keep" decision

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10 22:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("images", sa.Column("duplicate_score", sa.Float(), nullable=True))
    op.add_column("images", sa.Column("duplicate_keep", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_column("images", "duplicate_keep")
    op.drop_column("images", "duplicate_score")
