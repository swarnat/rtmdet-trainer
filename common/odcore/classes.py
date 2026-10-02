"""Detection classes: managed in the ``detection_classes`` table.

Classes are configured inside the application (name, label, colour, order,
optional COCO source classes). A class name is an immutable identifier: it is
referenced by annotations, training runs and model versions. Every model
version freezes the ordered list of classes it was trained with.
"""
from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import DetectionClass

CLASS_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# The 80 COCO detection classes in the order used by MMDetection checkpoints.
COCO_CLASSES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)

# Initial classes (seeded by the migration). Trains/rail vehicles are
# intentionally NOT mapped to "vehicle".
DEFAULT_CLASSES: list[dict] = [
    {"name": "person", "label": "Person", "color": "#e53935", "coco_classes": ["person"]},
    {"name": "bicycle", "label": "Fahrrad", "color": "#1e88e5", "coco_classes": ["bicycle"]},
    {"name": "vehicle", "label": "Fahrzeug", "color": "#fb8c00", "coco_classes": ["car", "motorcycle", "bus", "truck"]},
]

# Colours offered for new classes (cycled)
PALETTE = ["#e53935", "#1e88e5", "#fb8c00", "#43a047", "#8e24aa", "#00acc1", "#fdd835", "#6d4c41", "#d81b60", "#3949ab"]


def validate_class_name(name: str) -> str:
    if not CLASS_NAME_RE.match(name or ""):
        raise ValueError(
            f"invalid class name '{name}': lowercase letters, digits and '_', starting with a letter, max. 32 characters"
        )
    return name


def validate_coco_sources(sources: Iterable[str]) -> list[str]:
    result: list[str] = []
    for src in sources:
        if src not in COCO_CLASSES:
            raise ValueError(f"unknown COCO class '{src}'")
        if src not in result:
            result.append(src)
    return result


def list_classes(session: Session, active_only: bool = False) -> list[DetectionClass]:
    stmt = select(DetectionClass).order_by(DetectionClass.sort_order, DetectionClass.id)
    if active_only:
        stmt = stmt.where(DetectionClass.active.is_(True))
    return list(session.execute(stmt).scalars())


def active_class_names(session: Session) -> list[str]:
    return [c.name for c in list_classes(session, active_only=True)]


def coco_index_mapping(classes: Iterable[DetectionClass]) -> dict[str, list[int]]:
    """``{class name: [COCO indices]}`` for classes that have COCO sources."""
    return {c.name: [COCO_CLASSES.index(s) for s in c.coco_classes] for c in classes if c.coco_classes}


def is_reviewed_for(reviewed: Iterable[str] | None, class_names: Iterable[str]) -> bool:
    """An image can be used for a class set only if it was checked for every class in it."""
    return set(class_names) <= set(reviewed or ())
