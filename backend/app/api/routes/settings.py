from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from odcore.architectures import get_base_model
from odcore.geometry import parse_input_size
from odcore.settings_store import DEFAULT_SETTINGS, SECRET_MASK, SECRET_SETTINGS, get_all_settings, set_setting

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
    if key == "camera_groups_use_metadata":
        if not isinstance(value, bool):
            raise ValueError("camera_groups_use_metadata must be true or false")
        return value
    if key == "duplicate_max_difference":
        value = float(value)
        if not 0.01 <= value <= 1.0:
            raise ValueError("duplicate_max_difference must be in [0.01, 1]")
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
    if key == "default_base_model":
        get_base_model(str(value))  # raises KeyError for unknown ids
        return value
    if key in ("deployment_url", "client_annotator_url", "client_inference_url"):
        value = str(value).strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError(f"{key} must start with http:// or https://")
        return value
    if key in ("deployment_access_key", "client_annotator_access_key"):
        value = str(value).strip()
        if value and len(value) < 16:
            raise ValueError(f"{key} must have at least 16 characters")
        return value
    if key == "validation_ratio":
        value = float(value)
        if not 0.0 < value < 1.0:
            raise ValueError("validation_ratio must be in (0, 1)")
        return value
    return value


def _out(session: Session) -> SettingsOut:
    values = get_all_settings(session)
    for key in SECRET_SETTINGS:  # secrets are write-only
        values[key] = SECRET_MASK if values.get(key) else ""
    return SettingsOut(values=values, defaults=DEFAULT_SETTINGS)


@router.get("", response_model=SettingsOut, summary="Current settings (secrets masked)")
def get_settings(session: Session = Depends(get_db)) -> SettingsOut:
    return _out(session)


@router.put("", response_model=SettingsOut, summary="Update settings (partial)")
def update_settings(body: SettingsUpdate, session: Session = Depends(get_db)) -> SettingsOut:
    # an unchanged masked secret means "keep the stored value"
    values = {k: v for k, v in body.values.items() if not (k in SECRET_SETTINGS and v == SECRET_MASK)}
    try:
        cleaned = {k: _validate(k, v) for k, v in values.items()}
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for key, value in cleaned.items():
        set_setting(session, key, value)
    session.commit()
    return _out(session)
