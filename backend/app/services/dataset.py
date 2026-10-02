"""Dataset statistics and training eligibility (the snapshot itself is built by the trainer)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from odcore.classes import active_class_names, is_reviewed_for, list_classes
from odcore.db import Annotation, AnnotationStatus, DatasetSplit, Image


def _labeled_rows(session: Session) -> list[tuple[int, DatasetSplit | None, list[str] | None]]:
    return list(
        session.execute(
            select(Image.id, Image.dataset_split, Image.reviewed_classes).where(Image.annotation_status == AnnotationStatus.labeled)
        ).all()
    )


def needs_review_ids(session: Session, class_names: list[str] | None = None) -> list[int]:
    """Labeled images not checked for all given (default: all active) classes."""
    names = class_names if class_names is not None else active_class_names(session)
    return [i for i, _split, reviewed in _labeled_rows(session) if not is_reviewed_for(reviewed, names)]


def eligibility(session: Session, class_names: list[str]) -> dict:
    """Which labeled images a training with ``class_names`` can use."""
    usable = {"train": 0, "validation": 0}
    usable_ids = []
    needs_review = 0
    for image_id, split, reviewed in _labeled_rows(session):
        if not is_reviewed_for(reviewed, class_names):
            needs_review += 1
        elif split is not None:
            usable[split.value] += 1
            usable_ids.append(image_id)
    with_boxes = set(
        session.execute(
            select(Annotation.image_id).where(Annotation.class_name.in_(class_names)).distinct()
        ).scalars()
    )
    negative = sum(1 for i in usable_ids if i not in with_boxes)
    return {"class_names": class_names, "usable": usable, "needs_review": needs_review, "negative": negative}


def dataset_stats(session: Session) -> dict:
    total = session.scalar(select(func.count(Image.id))) or 0
    rows = _labeled_rows(session)
    active = active_class_names(session)

    with_boxes = set(session.execute(select(Annotation.image_id).distinct()).scalars())
    splits = {"train": 0, "validation": 0}
    for _id, split, _reviewed in rows:
        if split is not None:
            splits[split.value] += 1

    class_rows = dict(
        session.execute(
            select(Annotation.class_name, func.count(Annotation.id))
            .join(Image, Image.id == Annotation.image_id)
            .where(Image.annotation_status == AnnotationStatus.labeled)
            .group_by(Annotation.class_name)
        ).all()
    )
    per_class = {c.name: class_rows.get(c.name, 0) for c in list_classes(session)}

    return {
        "images_total": total,
        "images_labeled": len(rows),
        "images_unlabeled": total - len(rows),
        "images_negative": sum(1 for i, *_ in rows if i not in with_boxes),
        "images_needs_review": sum(1 for _i, _s, reviewed in rows if not is_reviewed_for(reviewed, active)),
        "splits": splits,
        "annotations_per_class": per_class,
    }
