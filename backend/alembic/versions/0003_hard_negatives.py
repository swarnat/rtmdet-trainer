"""hard negative annotations

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03 14:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("annotations", sa.Column("type", sa.String(length=16), server_default="positive", nullable=False))
    op.add_column("annotations", sa.Column("source_confidence", sa.Float(), nullable=True))
    op.add_column("annotations", sa.Column("source_model", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_annotations_type"), "annotations", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_annotations_type"), table_name="annotations")
    op.drop_column("annotations", "source_model")
    op.drop_column("annotations", "source_confidence")
    op.drop_column("annotations", "type")
