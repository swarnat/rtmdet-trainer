"""Application settings stored in the ``settings`` table with code defaults."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from .db import Setting

DEFAULT_SETTINGS: dict[str, Any] = {
    # Default model input resolution for inference/training (WIDTHxHEIGHT, multiples of 32)
    "default_input_size": "1536x864",
    # Resolutions offered in the UI
    "input_sizes": ["1536x864", "1280x736", "1024x576", "1920x1088", "768x448"],
    "default_confidence": 0.25,
    # base model preselected in the training dialog (rtmdet-tiny-coco | rtmdet-s-coco | rtmdet-m-coco)
    "default_base_model": "rtmdet-s-coco",
    "nms_iou_threshold": 0.6,
    # Fraction of newly labeled images assigned to the validation split (persisted per image)
    "validation_ratio": 0.15,
    # Confidence used for precision/recall and the hard-negative regression in the training evaluation
    "eval_confidence": 0.25,
    # Hard negatives: crop = box x factor (each side), widened to 16:9, at least this fraction of the image width
    "hard_negative_context_factor": 3.0,
    "hard_negative_min_crop_fraction": 0.25,
    # how often each hard-negative crop appears in the training split
    "hard_negative_oversample": 3,
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
