"""Dataset statistics (the reproducible snapshot itself is built by the trainer)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from odcore.classes import CLASS_NAMES
from odcore.db import Annotation, AnnotationStatus, Image


def dataset_stats(session: Session) -> dict:
    total = session.scalar(select(func.count(Image.id))) or 0
    labeled = session.scalar(select(func.count(Image.id)).where(Image.annotation_status == AnnotationStatus.labeled)) or 0

    ann_count = (
        select(Annotation.image_id, func.count(Annotation.id).label("n")).group_by(Annotation.image_id).subquery()
    )
    negatives = session.scalar(
        select(func.count(Image.id))
        .outerjoin(ann_count, ann_count.c.image_id == Image.id)
        .where(Image.annotation_status == AnnotationStatus.labeled, ann_count.c.n.is_(None))
    ) or 0

    split_rows = session.execute(
        select(Image.dataset_split, func.count(Image.id))
        .where(Image.annotation_status == AnnotationStatus.labeled)
        .group_by(Image.dataset_split)
    ).all()
    splits = {"train": 0, "validation": 0}
    for split, n in split_rows:
        if split is not None:
            splits[split.value] = n

    class_rows = session.execute(
        select(Annotation.class_name, func.count(Annotation.id))
        .join(Image, Image.id == Annotation.image_id)
        .where(Image.annotation_status == AnnotationStatus.labeled)
        .group_by(Annotation.class_name)
    ).all()
    per_class = {name: 0 for name in CLASS_NAMES}
    per_class.update({name: n for name, n in class_rows})

    return {
        "images_total": total,
        "images_labeled": labeled,
        "images_unlabeled": total - labeled,
        "images_negative": negatives,
        "splits": splits,
        "annotations_per_class": per_class,
    }
