"""Saving annotations and managing the labeling status of images."""
from __future__ import annotations

from sqlalchemy.orm import Session

from odcore.db import Annotation, AnnotationStatus, DatasetSplit, Image, utcnow
from odcore.geometry import normalize_box
from odcore.settings_store import get_setting
from odcore.splits import assign_split

from app.schemas.annotation import AnnotationIn


class AnnotationValidationError(ValueError):
    pass


def ensure_split(session: Session, image: Image) -> None:
    """Assign the train/validation split once; never re-rolled afterwards."""
    if image.dataset_split is None:
        ratio = float(get_setting(session, "validation_ratio"))
        image.dataset_split = DatasetSplit(assign_split(image.sha256, ratio))


def replace_annotations(session: Session, image: Image, items: list[AnnotationIn], mark_labeled: bool) -> Image:
    """Replace all boxes of an image. An empty list + mark_labeled = negative example."""
    new_boxes = []
    for index, item in enumerate(items):
        try:
            x1, y1, x2, y2 = normalize_box(item.x1, item.y1, item.x2, item.y2, image.width, image.height)
        except ValueError as exc:
            raise AnnotationValidationError(f"annotation #{index}: {exc}") from exc
        new_boxes.append(
            Annotation(
                class_name=item.class_name,
                x1=round(x1, 1), y1=round(y1, 1), x2=round(x2, 1), y2=round(y2, 1),
                source=item.source,
            )
        )
    image.annotations.clear()
    session.flush()
    image.annotations.extend(new_boxes)
    if mark_labeled:
        image.annotation_status = AnnotationStatus.labeled
        image.labeled_at = utcnow()
        ensure_split(session, image)
    image.updated_at = utcnow()
    session.commit()
    session.refresh(image)
    return image


def set_status(session: Session, image: Image, status: AnnotationStatus) -> None:
    image.annotation_status = status
    if status == AnnotationStatus.labeled:
        image.labeled_at = utcnow()
        ensure_split(session, image)
    else:
        image.labeled_at = None
    image.updated_at = utcnow()
