"""tombstones for deleted images: a re-upload of the same file is rejected

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-11 14:00:00

Images that are already hidden (deleted but kept for training snapshots) get a tombstone too.
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deleted_images",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.execute(
        "INSERT INTO deleted_images (sha256, original_filename, deleted_at) "
        "SELECT sha256, original_filename, deleted_at FROM images WHERE deleted_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_table("deleted_images")
