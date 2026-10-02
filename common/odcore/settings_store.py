"""Application settings stored in the ``settings`` table with code defaults."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from .classes import DEFAULT_COCO_MAPPING
from .db import Setting

DEFAULT_SETTINGS: dict[str, Any] = {
    # Default model input resolution for inference/training (WIDTHxHEIGHT, multiples of 32)
    "default_input_size": "1536x864",
    # Resolutions offered in the UI
    "input_sizes": ["1536x864", "1280x736", "1024x576", "1920x1088", "768x448"],
    "default_confidence": 0.25,
    "nms_iou_threshold": 0.6,
    # Fraction of newly labeled images assigned to the validation split (persisted per image)
    "validation_ratio": 0.15,
    # target class -> COCO classes, used for the COCO bootstrap model and head initialisation
    "coco_class_mapping": DEFAULT_COCO_MAPPING,
    # Confidence used for precision/recall in the training evaluation
    "eval_confidence": 0.25,
}


def get_setting(session: Session, key: str) -> Any:
    row = session.get(Setting, key)
    if row is not None:
        return row.value
    if key not in DEFAULT_SETTINGS:
        raise KeyError(key)
    return copy.deepcopy(DEFAULT_SETTINGS[key])


def get_all_settings(session: Session) -> dict[str, Any]:
    values = copy.deepcopy(DEFAULT_SETTINGS)
    for row in session.query(Setting).all():
        values[row.key] = row.value
    return values


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
