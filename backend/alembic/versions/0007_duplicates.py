"""duplicate check of empty images: thumbnail fingerprint and duplicate_of

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-10 20:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("images", sa.Column("fingerprint", sa.LargeBinary(), nullable=True))
    op.add_column("images", sa.Column("duplicate_of", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_images_duplicate_of", "images", "images", ["duplicate_of"], ["id"], ondelete="SET NULL")
    op.create_index("ix_images_duplicate_of", "images", ["duplicate_of"])


def downgrade() -> None:
    op.drop_index("ix_images_duplicate_of", table_name="images")
    op.drop_constraint("fk_images_duplicate_of", "images", type_="foreignkey")
    op.drop_column("images", "duplicate_of")
    op.drop_column("images", "fingerprint")
