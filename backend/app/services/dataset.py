"""Dataset statistics and training eligibility (the snapshot itself is built by the trainer)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from odcore.classes import active_class_names, is_reviewed_for, list_classes
from odcore.db import Annotation, AnnotationStatus, DatasetSplit, Image


def _labeled_rows(session: Session, include_duplicates: bool = True) -> list[tuple[int, DatasetSplit | None, list[str] | None]]:
    stmt = select(Image.id, Image.dataset_split, Image.reviewed_classes).where(
        Image.annotation_status == AnnotationStatus.labeled, Image.deleted_at.is_(None)
    )
    if not include_duplicates:  # as the trainer: duplicate empty images are not used
        stmt = stmt.where(Image.duplicate_of.is_(None))
    return list(session.execute(stmt).all())


def needs_review_ids(session: Session, class_names: list[str] | None = None) -> list[int]:
    """Labeled images not checked for all given (default: all active) classes."""
    names = class_names if class_names is not None else active_class_names(session)
    return [i for i, _split, reviewed in _labeled_rows(session) if not is_reviewed_for(reviewed, names)]


def eligibility(session: Session, class_names: list[str]) -> dict:
    """Which labeled images a training with ``class_names`` can use."""
    usable = {"train": 0, "validation": 0}
    usable_ids = []
    needs_review = 0
    for image_id, split, reviewed in _labeled_rows(session, include_duplicates=False):
        if not is_reviewed_for(reviewed, class_names):
            needs_review += 1
        elif split is not None:
            usable[split.value] += 1
            usable_ids.append(image_id)
    rows = session.execute(
        select(Annotation.image_id, Annotation.type).where(Annotation.class_name.in_(class_names))
    ).all()
    with_boxes = {i for i, kind in rows if kind == "positive"}
    usable_set = set(usable_ids)
    hard_negatives = sum(1 for i, kind in rows if kind == "hard_negative" and i in usable_set)
    negative = sum(1 for i in usable_ids if i not in with_boxes)
    duplicates = session.scalar(
        select(func.count(Image.id)).where(
            Image.annotation_status == AnnotationStatus.labeled, Image.deleted_at.is_(None), Image.duplicate_of.is_not(None)
        )
    ) or 0
    return {"class_names": class_names, "usable": usable, "needs_review": needs_review, "negative": negative,
            "hard_negatives": hard_negatives, "duplicates": duplicates}


def dataset_stats(session: Session) -> dict:
    total = session.scalar(select(func.count(Image.id)).where(Image.deleted_at.is_(None))) or 0
    hidden = session.scalar(select(func.count(Image.id)).where(Image.deleted_at.is_not(None))) or 0
    rows = _labeled_rows(session)
    active = active_class_names(session)

    with_boxes = set(session.execute(select(Annotation.image_id).where(Annotation.type == "positive").distinct()).scalars())
    splits = {"train": 0, "validation": 0}
    for _id, split, _reviewed in rows:
        if split is not None:
            splits[split.value] += 1

    class_rows = session.execute(
        select(Annotation.class_name, Annotation.type, func.count(Annotation.id))
        .join(Image, Image.id == Annotation.image_id)
        .where(Image.annotation_status == AnnotationStatus.labeled)
        .group_by(Annotation.class_name, Annotation.type)
    ).all()
    counts = {(name, kind): n for name, kind, n in class_rows}
    classes = list_classes(session)
    per_class = {c.name: counts.get((c.name, "positive"), 0) for c in classes}
    hard_negatives = {c.name: counts.get((c.name, "hard_negative"), 0) for c in classes}

    return {
        "images_total": total,
        "images_labeled": len(rows),
        "images_unlabeled": total - len(rows),
        "images_negative": sum(1 for i, *_ in rows if i not in with_boxes),
        "images_needs_review": sum(1 for _i, _s, reviewed in rows if not is_reviewed_for(reviewed, active)),
        # empty images marked as duplicates (duplicate check), not used for training
        "images_duplicates": session.scalar(
            select(func.count(Image.id)).where(Image.deleted_at.is_(None), Image.duplicate_of.is_not(None))
        ) or 0,
        "splits": splits,
        "annotations_per_class": per_class,
        "hard_negatives_per_class": hard_negatives,
        # deleted images whose files are kept because training snapshots still use them
        "images_retained_for_snapshots": hidden,
    }
