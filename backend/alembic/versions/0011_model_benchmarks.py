"""model benchmarks: all models on the current validation set

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-11 16:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "model_benchmarks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "completed", "failed", "cancelled", name="batch_status",
                                    native_enum=False, length=32), nullable=False),
        sa.Column("class_names", JSONType, nullable=True),
        sa.Column("num_images", sa.Integer(), nullable=False),
        sa.Column("num_boxes", sa.Integer(), nullable=False),
        sa.Column("num_hard_negatives", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("results_json", JSONType, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("model_benchmarks")
