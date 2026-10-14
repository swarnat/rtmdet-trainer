"""Annotation review: every annotated box as a small crop, per class, for a quick visual check."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from odcore.db import Annotation, DatasetSplit, Image
from odcore.storage import ObjectStorage

from app.core.database import get_db
from app.core.s3 import get_storage
from app.schemas.annotation import ReviewClassCount, ReviewCrop, ReviewCropList
from app.services.annotation_crops import CROP_MARGIN, crop_jpeg, decoded_cache

router = APIRouter(prefix="/annotations", tags=["annotation review"])

_live = Image.deleted_at.is_(None)
_width = Annotation.x2 - Annotation.x1
_height = Annotation.y2 - Annotation.y1
SORTS = {
    "newest": (Annotation.updated_at.desc(), Annotation.id.desc()),
    "oldest": (Annotation.updated_at, Annotation.id),
    "smallest": (_width * _height, Annotation.id),
    "largest": ((_width * _height).desc(), Annotation.id),
    # extreme aspect ratios first: lying/cut-off persons, boxes around two objects ...
    "widest": ((_width / func.nullif(_height, 0)).desc(), Annotation.id),
    "tallest": ((_width / func.nullif(_height, 0)), Annotation.id),
    "image": (Annotation.image_id, Annotation.id),
}


@router.get("/review/classes", response_model=list[ReviewClassCount], summary="Number of annotated boxes per class")
def review_classes(session: Session = Depends(get_db)) -> list[ReviewClassCount]:
    rows = session.execute(
        select(Annotation.class_name, Annotation.type, func.count())
        .join(Image, Image.id == Annotation.image_id).where(_live)
        .group_by(Annotation.class_name, Annotation.type)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for name, typ, n in rows:
        counts.setdefault(name, {"positive": 0, "hard_negative": 0})[typ] = n
    return [ReviewClassCount(class_name=k, positive=v.get("positive", 0), hard_negative=v.get("hard_negative", 0))
            for k, v in sorted(counts.items())]


@router.get("/review", response_model=ReviewCropList, summary="Annotated boxes of one class (for crops)")
def review_list(
    class_name: str = Query(..., alias="class"),
    type: Literal["positive", "hard_negative"] = "positive",
    split: Optional[Literal["train", "validation"]] = None,
    sort: Literal["newest", "oldest", "smallest", "largest", "widest", "tallest", "image"] = "newest",
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    session: Session = Depends(get_db),
) -> ReviewCropList:
    where = [_live, Annotation.class_name == class_name, Annotation.type == type]
    if split:
        where.append(Image.dataset_split == DatasetSplit(split))
    base = select(Annotation, Image.width, Image.height, Image.dataset_split).join(Image, Image.id == Annotation.image_id).where(*where)
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = session.execute(base.order_by(*SORTS[sort]).offset(offset).limit(limit)).all()
    items = [
        ReviewCrop(id=a.id, image_id=a.image_id, class_name=a.class_name, x1=a.x1, y1=a.y1, x2=a.x2, y2=a.y2, type=a.type,
                   source=a.source, image_width=w, image_height=h, dataset_split=s.value if s else None, updated_at=a.updated_at)
        for a, w, h, s in rows
    ]
    return ReviewCropList(total=total, margin=CROP_MARGIN, items=items)


@router.get("/{annotation_id}/crop", summary="JPEG crop of the box plus 20 px context", response_class=Response)
def annotation_crop(annotation_id: int, session: Session = Depends(get_db),
                          storage: ObjectStorage = Depends(get_storage)) -> Response:
    row = session.execute(
        select(Annotation, Image.s3_object_key).join(Image, Image.id == Annotation.image_id)
        .where(Annotation.id == annotation_id, _live)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"annotation {annotation_id} not found")
    a, key = row

    image = decoded_cache.get(a.image_id, lambda: storage.get_bytes(storage.settings.bucket_images, key))
    data = crop_jpeg(image, (a.x1, a.y1, a.x2, a.y2))
    # the URL carries the annotation's updated_at (?v=...), so an edited box gets a new URL
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
