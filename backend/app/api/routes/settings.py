from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from odcore.geometry import parse_input_size
from odcore.settings_store import DEFAULT_SETTINGS, get_all_settings, set_setting

from app.core.database import get_db
from app.schemas.settings import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def _validate(key: str, value: Any) -> Any:
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"unknown setting '{key}'")
    if key == "default_input_size":
        w, h = parse_input_size(str(value))
        return f"{w}x{h}"
    if key == "input_sizes":
        if not isinstance(value, list) or not value:
            raise ValueError("input_sizes must be a non-empty list")
        return [f"{w}x{h}" for w, h in (parse_input_size(str(v)) for v in value)]
    if key in ("default_confidence", "eval_confidence", "nms_iou_threshold"):
        value = float(value)
        if not 0.0 < value <= 1.0:
            raise ValueError(f"{key} must be in (0, 1]")
        return value
    if key == "hard_negative_context_factor":
        value = float(value)
        if not 1.0 <= value <= 10.0:
            raise ValueError("hard_negative_context_factor must be in [1, 10]")
        return value
    if key == "hard_negative_min_crop_fraction":
        value = float(value)
        if not 0.05 <= value <= 1.0:
            raise ValueError("hard_negative_min_crop_fraction must be in [0.05, 1]")
        return value
    if key == "hard_negative_oversample":
        value = int(value)
        if not 0 <= value <= 20:
            raise ValueError("hard_negative_oversample must be in [0, 20] (0 = no crops)")
        return value
    if key == "validation_ratio":
        value = float(value)
        if not 0.0 < value < 1.0:
            raise ValueError("validation_ratio must be in (0, 1)")
        return value
    return value


@router.get("", response_model=SettingsOut, summary="Current settings")
def get_settings(session: Session = Depends(get_db)) -> SettingsOut:
    return SettingsOut(values=get_all_settings(session), defaults=DEFAULT_SETTINGS)


@router.put("", response_model=SettingsOut, summary="Update settings (partial)")
def update_settings(body: SettingsUpdate, session: Session = Depends(get_db)) -> SettingsOut:
    try:
        cleaned = {k: _validate(k, v) for k, v in body.values.items()}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for key, value in cleaned.items():
        set_setting(session, key, value)
    session.commit()
    return SettingsOut(values=get_all_settings(session), defaults=DEFAULT_SETTINGS)
