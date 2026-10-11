from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from odcore.db import Annotation, AnnotationStatus, DatasetSplit, Image, ImageErrorMark, ImageSuggestion


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
    duplicates_only: bool = False,
    exclude_ids: Optional[list[int]] = None,
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
    if duplicates_only:
        stmt = stmt.where(Image.duplicate_of.is_not(None))
    if exclude_ids:
        stmt = stmt.where(Image.id.not_in(exclude_ids))
    if negative_only:
        stmt = stmt.where(
            Image.annotation_status == AnnotationStatus.labeled,
            # negative = no real objects (hard negatives don't count as objects)
            ~select(Annotation.id).where(Annotation.image_id == Image.id, Annotation.type == "positive").exists(),
        )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = session.execute(stmt.order_by(Image.id).offset(offset).limit(limit)).scalars().all()
    return total, list(items)


def ids_with_suggestions(session: Session) -> list[int]:
    """Images whose latest batch test produced at least one suggestion."""
    rows = session.execute(select(ImageSuggestion.image_id, ImageSuggestion.detections_json)).all()
    return [image_id for image_id, dets in rows if dets]


# suggestion confidence levels, by the *lowest* confidence of an image's suggestions (the weakest one decides
# how carefully the image has to be checked)
SUGGESTION_LEVELS = {"high": (0.7, None), "medium": (0.4, 0.7), "low": (None, 0.4)}


def ids_with_suggestion_level(session: Session, level: str) -> list[int]:
    lo, hi = SUGGESTION_LEVELS[level]
    out = []
    for image_id, dets in session.execute(select(ImageSuggestion.image_id, ImageSuggestion.detections_json)):
        if not dets:
            continue
        weakest = min(float(d["confidence"]) for d in dets)
        if (lo is None or weakest >= lo) and (hi is None or weakest < hi):
            out.append(image_id)
    return out


LAST_UPLOAD_GAP = timedelta(minutes=30)


def last_upload_ids(session: Session, gap: timedelta = LAST_UPLOAD_GAP) -> list[int]:
    """Images of the most recent upload session: newest upload back to the first pause longer than ``gap``."""
    rows = session.execute(
        select(Image.id, Image.created_at).where(Image.deleted_at.is_(None)).order_by(Image.created_at.desc())
    ).all()
    ids: list[int] = []
    previous = None
    for image_id, created in rows:
        if previous is not None and previous - created > gap:
            break
        ids.append(image_id)
        previous = created
    return ids


def error_marked_ids(session: Session) -> list[int]:
    return list(session.execute(select(ImageErrorMark.image_id)).scalars())


def neighbour_ids(
    session: Session, image_id: int, status: Optional[AnnotationStatus], split: Optional[DatasetSplit] = None,
    has_errors: bool = False,
    duplicates_only: bool = False,
    exclude_ids: Optional[list[int]] = None,
    only_ids: Optional[list[int]] = None,
) -> tuple[Optional[int], Optional[int]]:
    base = select(Image.id).where(Image.deleted_at.is_(None))
    if only_ids is not None:
        base = base.where(Image.id.in_(only_ids))
    if exclude_ids:
        base = base.where(Image.id.not_in(exclude_ids))
    if duplicates_only:
        base = base.where(Image.duplicate_of.is_not(None))
    if has_errors:
        base = base.where(Image.id.in_(select(ImageErrorMark.image_id)))
    if status is not None:
        base = base.where(Image.annotation_status == status)
    if split is not None:
        base = base.where(Image.dataset_split == split)
    prev_id = session.scalar(base.where(Image.id < image_id).order_by(Image.id.desc()).limit(1))
    next_id = session.scalar(base.where(Image.id > image_id).order_by(Image.id.asc()).limit(1))
    return prev_id, next_id


def get_by_sha(session: Session, sha256: str) -> Optional[Image]:
    """Also returns a hidden (deleted but still linked) image."""
    return session.execute(select(Image).where(Image.sha256 == sha256)).scalars().first()
