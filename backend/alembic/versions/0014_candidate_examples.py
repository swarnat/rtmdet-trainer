"""candidate searches by example boxes

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23 16:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("candidate_searches", sa.Column("mode", sa.String(length=16), server_default="text", nullable=False))
    op.add_column("candidate_searches", sa.Column("exemplars", JSONType, server_default=sa.text("'[]'"), nullable=False))


def downgrade() -> None:
    op.drop_column("candidate_searches", "exemplars")
    op.drop_column("candidate_searches", "mode")
