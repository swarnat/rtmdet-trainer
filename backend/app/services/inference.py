"""Detection use case shared by ``/detect`` and the annotation test function."""
from __future__ import annotations

import logging

import numpy as np
from sqlalchemy.orm import Session

from odcore.geometry import parse_input_size
from odcore.settings_store import get_setting

from app.schemas.detection import BBox, DetectionOut, DetectResponse, ImageInfo, ModelInfo
from app.services.model_registry import ModelRegistry, resolve_model

log = logging.getLogger(__name__)


class InvalidRequestError(ValueError):
    pass


def resolve_parameters(session: Session, input_size: str | None, confidence: float | None) -> tuple[int, int, float]:
    try:
        width, height = parse_input_size(input_size or get_setting(session, "default_input_size"))
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    if confidence is None:
        confidence = float(get_setting(session, "default_confidence"))
    if not 0.0 < confidence <= 1.0:
        raise InvalidRequestError("confidence must be in (0, 1]")
    return width, height, confidence


def run_detection(
    session: Session,
    registry: ModelRegistry,
    image: np.ndarray,
    model: str | None = None,
    input_size: str | None = None,
    confidence: float | None = None,
) -> DetectResponse:
    width, height, conf = resolve_parameters(session, input_size, confidence)
    iou = float(get_setting(session, "nms_iou_threshold"))
    ref = resolve_model(session, model)
    # Release the DB connection before the (comparatively slow) inference
    session.close()

    detector = registry.get_detector(ref, width, height)
    result = detector.detect(image, conf, iou)
    detections = [
        DetectionOut(
            class_name=ref.class_names[d.class_id],
            confidence=round(d.confidence, 4),
            bbox=BBox(x1=round(d.x1), y1=round(d.y1), x2=round(d.x2), y2=round(d.y2)),
        )
        for d in result.detections
    ]
    return DetectResponse(
        image=ImageInfo(width=int(image.shape[1]), height=int(image.shape[0])),
        model=ModelInfo(version=ref.version, status=ref.status, input_width=width, input_height=height),
        inference_ms=round(result.inference_ms, 1),
        detections=detections,
    )
