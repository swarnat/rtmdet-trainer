"""error analysis: images on which a model produced false positives / false negatives

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10 12:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("prediction_batches", sa.Column("marked_images", sa.Integer(), server_default="0", nullable=False))
    op.create_table(
        "image_error_marks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("input_width", sa.Integer(), nullable=False),
        sa.Column("input_height", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("true_positives", sa.Integer(), nullable=False),
        sa.Column("false_positives_json", JSONType, nullable=False),
        sa.Column("false_negatives_json", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["prediction_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("image_id"),
    )
    op.create_index(op.f("ix_image_error_marks_batch_id"), "image_error_marks", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_image_error_marks_batch_id"), table_name="image_error_marks")
    op.drop_table("image_error_marks")
    op.drop_column("prediction_batches", "marked_images")
