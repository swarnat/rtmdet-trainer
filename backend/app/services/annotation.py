"""Saving annotations and managing the labeling status of images."""
from __future__ import annotations

from sqlalchemy.orm import Session

from odcore.classes import active_class_names, list_classes
from sqlalchemy import delete

from odcore.db import Annotation, AnnotationStatus, DatasetSplit, Image, ImageErrorMark, ImageSuggestion, utcnow
from odcore.geometry import normalize_box
from odcore.settings_store import get_setting
from odcore.splits import assign_split

from app.schemas.annotation import AnnotationIn
from app.services.duplicates import clear_marks_for


class AnnotationValidationError(ValueError):
    pass


def ensure_split(session: Session, image: Image) -> None:
    """Assign the train/validation split once; never re-rolled afterwards."""
    if image.dataset_split is None:
        ratio = float(get_setting(session, "validation_ratio"))
        image.dataset_split = DatasetSplit(assign_split(image.sha256, ratio))


def mark_reviewed(session: Session, image: Image) -> None:
    """Saving as labeled confirms the image was checked for all currently active classes."""
    image.annotation_status = AnnotationStatus.labeled
    image.labeled_at = utcnow()
    image.reviewed_classes = active_class_names(session)
    ensure_split(session, image)
    # batch-test suggestions and error-analysis marks have been dealt with
    session.execute(delete(ImageSuggestion).where(ImageSuggestion.image_id == image.id))
    session.execute(delete(ImageErrorMark).where(ImageErrorMark.image_id == image.id))


def replace_annotations(session: Session, image: Image, items: list[AnnotationIn], mark_labeled: bool) -> Image:
    """Replace all boxes of an image. An empty list + mark_labeled = negative example."""
    known = {c.name for c in list_classes(session)}
    new_boxes = []
    for index, item in enumerate(items):
        if item.class_name not in known:
            raise AnnotationValidationError(f"annotation #{index}: unknown class '{item.class_name}'")
        try:
            x1, y1, x2, y2 = normalize_box(item.x1, item.y1, item.x2, item.y2, image.width, image.height)
        except ValueError as exc:
            raise AnnotationValidationError(f"annotation #{index}: {exc}") from exc
        hard = item.type == "hard_negative"
        new_boxes.append(
            Annotation(
                class_name=item.class_name,
                x1=round(x1, 1), y1=round(y1, 1), x2=round(x2, 1), y2=round(y2, 1),
                type=item.type,
                reflected=item.reflected,
                source=item.source,
                source_confidence=item.source_confidence if hard else None,
                source_model=item.source_model if hard else None,
            )
        )
    image.annotations.clear()
    session.flush()
    image.annotations.extend(new_boxes)
    if new_boxes:
        clear_marks_for(session, image)  # not an empty image any more
    if mark_labeled:
        mark_reviewed(session, image)
    image.updated_at = utcnow()
    session.commit()
    session.refresh(image)
    return image


def set_status(session: Session, image: Image, status: AnnotationStatus) -> None:
    if status == AnnotationStatus.labeled:
        mark_reviewed(session, image)
    else:
        image.annotation_status = status
        image.labeled_at = None
        image.reviewed_classes = None
    image.updated_at = utcnow()
