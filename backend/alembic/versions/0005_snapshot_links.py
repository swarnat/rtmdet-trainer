"""dataset snapshots reference images instead of copying them (link table + link count, soft delete)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04 20:00:00

Existing snapshots (with image copies) are converted by the trainer on its next start
(``odcore.snapshots.convert_legacy_snapshots``), because that needs S3 access.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("images", sa.Column("snapshot_refs", sa.Integer(), server_default="0", nullable=False))
    op.add_column("images", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_images_deleted_at", "images", ["deleted_at"])
    op.create_table(
        "snapshot_images",
        sa.Column("training_run_id", sa.Integer(), sa.ForeignKey("training_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id"), nullable=False),
        sa.PrimaryKeyConstraint("training_run_id", "image_id"),
    )
    op.create_index("ix_snapshot_images_image_id", "snapshot_images", ["image_id"])


def downgrade() -> None:
    op.drop_index("ix_snapshot_images_image_id", table_name="snapshot_images")
    op.drop_table("snapshot_images")
    op.drop_index("ix_images_deleted_at", table_name="images")
    op.drop_column("images", "deleted_at")
    op.drop_column("images", "snapshot_refs")
