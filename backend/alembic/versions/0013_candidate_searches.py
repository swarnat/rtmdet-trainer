"""candidate searches: boxes proposed by an open-vocabulary detector for (new) classes

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-23 10:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "candidate_searches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(length=64), nullable=False),
        sa.Column("prompts", JSONType, nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("max_images", sa.Integer(), nullable=False),
        sa.Column("min_score", sa.Float(), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "completed", "failed", "cancelled", name="batch_status",
                                    native_enum=False, length=32), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("found", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("search_id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("x1", sa.Float(), nullable=False),
        sa.Column("y1", sa.Float(), nullable=False),
        sa.Column("x2", sa.Float(), nullable=False),
        sa.Column("y2", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("prompt", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["search_id"], ["candidate_searches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidates_search_id"), "candidates", ["search_id"], unique=False)
    op.create_index(op.f("ix_candidates_image_id"), "candidates", ["image_id"], unique=False)
    op.create_index("ix_candidates_search_status_score", "candidates", ["search_id", "status", "score"], unique=False)


def downgrade() -> None:
    op.drop_table("candidates")
    op.drop_table("candidate_searches")
