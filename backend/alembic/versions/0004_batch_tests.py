"""batch tests (prediction batches and per-image suggestions)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03 16:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "prediction_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "completed", "failed", "cancelled", name="batch_status",
                                    native_enum=False, length=32), nullable=False),
        sa.Column("model_ref", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=True),
        sa.Column("input_width", sa.Integer(), nullable=False),
        sa.Column("input_height", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("detections", sa.Integer(), nullable=False),
        sa.Column("failed_images", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "image_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("input_width", sa.Integer(), nullable=False),
        sa.Column("input_height", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("detections_json", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["prediction_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("image_id"),
    )
    op.create_index(op.f("ix_image_suggestions_batch_id"), "image_suggestions", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_image_suggestions_batch_id"), table_name="image_suggestions")
    op.drop_table("image_suggestions")
    op.drop_table("prediction_batches")
