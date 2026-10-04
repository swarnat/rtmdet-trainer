from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from odcore.db import Annotation, AnnotationStatus, DatasetSplit, Image


def annotation_counts(session: Session, image_ids: list[int]) -> dict[int, dict[str, int]]:
    """``{image id: {"positive": n, "hard_negative": m}}``"""
    if not image_ids:
        return {}
    rows = session.execute(
        select(Annotation.image_id, Annotation.type, func.count(Annotation.id))
        .where(Annotation.image_id.in_(image_ids))
        .group_by(Annotation.image_id, Annotation.type)
    ).all()
    result: dict[int, dict[str, int]] = {}
    for image_id, kind, n in rows:
        result.setdefault(image_id, {})[kind] = n
    return result


def list_images(
    session: Session,
    status: Optional[AnnotationStatus] = None,
    split: Optional[DatasetSplit] = None,
    negative_only: bool = False,
    restrict_ids: Optional[list[int]] = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[int, list[Image]]:
    stmt = select(Image).where(Image.deleted_at.is_(None))  # hidden: deleted, still used by a snapshot
    if status is not None:
        stmt = stmt.where(Image.annotation_status == status)
    if split is not None:
        stmt = stmt.where(Image.dataset_split == split)
    if restrict_ids is not None:
        stmt = stmt.where(Image.id.in_(restrict_ids))
    if negative_only:
        stmt = stmt.where(
            Image.annotation_status == AnnotationStatus.labeled,
            # negative = no real objects (hard negatives don't count as objects)
            ~select(Annotation.id).where(Annotation.image_id == Image.id, Annotation.type == "positive").exists(),
        )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = session.execute(stmt.order_by(Image.id).offset(offset).limit(limit)).scalars().all()
    return total, list(items)


def neighbour_ids(session: Session, image_id: int, status: Optional[AnnotationStatus]) -> tuple[Optional[int], Optional[int]]:
    base = select(Image.id).where(Image.deleted_at.is_(None))
    if status is not None:
        base = base.where(Image.annotation_status == status)
    prev_id = session.scalar(base.where(Image.id < image_id).order_by(Image.id.desc()).limit(1))
    next_id = session.scalar(base.where(Image.id > image_id).order_by(Image.id.asc()).limit(1))
    return prev_id, next_id


def get_by_sha(session: Session, sha256: str) -> Optional[Image]:
    """Also returns a hidden (deleted but still linked) image: an upload of the same content revives it."""
    return session.execute(select(Image).where(Image.sha256 == sha256)).scalars().first()
