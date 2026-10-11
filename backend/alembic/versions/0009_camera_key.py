"""camera identity from image metadata (EXIF serial number etc.)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-11 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("images", sa.Column("camera_key", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("images", "camera_key")
