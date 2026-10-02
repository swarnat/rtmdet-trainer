"""configurable detection classes

* table ``detection_classes`` (seeded with person/bicycle/vehicle; the COCO
  mapping is taken over from the former setting ``coco_class_mapping``)
* ``images.reviewed_classes``: classes an image was checked for
* ``training_runs.class_names``: class list of a run

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03 09:00:00
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

LEGACY = [
    ("person", "Person", "#e53935", ["person"]),
    ("bicycle", "Fahrrad", "#1e88e5", ["bicycle"]),
    ("vehicle", "Fahrzeug", "#fb8c00", ["car", "motorcycle", "bus", "truck"]),
]


def upgrade() -> None:
    classes = op.create_table(
        "detection_classes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("coco_classes", JSONType, nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("images", sa.Column("reviewed_classes", JSONType, nullable=True))
    op.add_column("training_runs", sa.Column("class_names", JSONType, nullable=True))

    conn = op.get_bind()
    mapping = {}
    row = conn.execute(sa.text("SELECT value FROM settings WHERE key = 'coco_class_mapping'")).first()
    if row is not None:
        mapping = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    op.bulk_insert(
        classes,
        [
            {"name": n, "label": label, "color": color, "coco_classes": mapping.get(n, coco), "sort_order": i, "active": True}
            for i, (n, label, color, coco) in enumerate(LEGACY)
        ],
    )
    legacy_names = json.dumps([n for n, *_ in LEGACY])
    # Images labeled so far were checked for exactly these three classes
    conn.execute(
        sa.text("UPDATE images SET reviewed_classes = CAST(:names AS JSONB) WHERE annotation_status = 'labeled'"),
        {"names": legacy_names},
    )
    conn.execute(sa.text("UPDATE training_runs SET class_names = CAST(:names AS JSONB)"), {"names": legacy_names})
    conn.execute(sa.text("DELETE FROM settings WHERE key = 'coco_class_mapping'"))


def downgrade() -> None:
    op.drop_column("training_runs", "class_names")
    op.drop_column("images", "reviewed_classes")
    op.drop_table("detection_classes")
