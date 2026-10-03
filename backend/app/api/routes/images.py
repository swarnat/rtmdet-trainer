from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from odcore.classes import active_class_names, is_reviewed_for
from sqlalchemy import select

from odcore.db import AnnotationStatus, DatasetSplit, Image, ImageSuggestion
from odcore.geometry import decode_image
from odcore.storage import ObjectStorage

from app.api.deps import read_upload
from app.api.routes.detect import detect_or_http_error
from app.core.database import get_db
from app.core.s3 import get_storage
from app.db.repositories import images as repo
from app.schemas.annotation import AnnotationOut, ImageDetail, ImageList, ImageOut, ImageUpdate, UploadResult
from app.schemas.batch_test import SuggestionOut
from app.schemas.detection import DetectResponse
from app.services import annotation as annotation_service
from app.services.dataset import dataset_stats, needs_review_ids
from app.services.model_registry import ModelRegistry, get_registry
from app.services.preprocessing import decode_upload, make_thumbnail

log = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["training images"])


def get_image_or_404(session: Session, image_id: int) -> Image:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"image {image_id} not found")
    return image


def to_out(image: Image, count: int, active: list[str] | None = None, hard_negatives: int = 0) -> ImageOut:
    out = ImageOut.model_validate(image)
    out.annotation_status = image.annotation_status.value
    out.dataset_split = image.dataset_split.value if image.dataset_split else None
    out.annotation_count = count
    out.hard_negative_count = hard_negatives
    out.needs_review = (
        active is not None
        and image.annotation_status == AnnotationStatus.labeled
        and not is_reviewed_for(image.reviewed_classes, active)
    )
    return out


def suggestions_for(session: Session, image_ids: list[int]) -> dict[int, ImageSuggestion]:
    if not image_ids:
        return {}
    rows = session.execute(select(ImageSuggestion).where(ImageSuggestion.image_id.in_(image_ids))).scalars()
    return {s.image_id: s for s in rows}


def to_detail(image: Image, active: list[str], session: Session) -> ImageDetail:
    positives = sum(1 for a in image.annotations if a.type == "positive")
    base = to_out(image, positives, active, len(image.annotations) - positives)
    suggestion = suggestions_for(session, [image.id]).get(image.id)
    base.suggestion_count = len(suggestion.detections_json) if suggestion else None
    return ImageDetail(
        **base.model_dump(),
        annotations=[AnnotationOut.model_validate(a) for a in image.annotations],
        suggestion=SuggestionOut.model_validate(suggestion) if suggestion else None,
    )


def store_upload(session: Session, storage: ObjectStorage, filename: Optional[str], data: bytes) -> UploadResult:
    try:
        decoded = decode_upload(data)
    except ValueError as exc:
        return UploadResult(filename=filename, status="error", error=str(exc))

    existing = repo.get_by_sha(session, decoded.sha256)
    if existing is not None:
        return UploadResult(filename=filename, status="duplicate", image=to_out(existing, sum(1 for a in existing.annotations if a.type == "positive")))

    bucket = storage.settings.bucket_images
    key = f"images/{decoded.sha256[:2]}/{decoded.sha256}{decoded.extension}"
    thumb_key = f"thumbnails/{decoded.sha256[:2]}/{decoded.sha256}.jpg"
    storage.put_bytes(bucket, key, decoded.data, decoded.content_type)
    storage.put_bytes(bucket, thumb_key, make_thumbnail(decoded.image), "image/jpeg")

    image = Image(
        s3_object_key=key,
        thumbnail_key=thumb_key,
        sha256=decoded.sha256,
        original_filename=(filename or "")[:512] or None,
        content_type=decoded.content_type,
        size_bytes=len(decoded.data),
        width=decoded.width,
        height=decoded.height,
        annotation_status=AnnotationStatus.unlabeled,
    )
    session.add(image)
    try:
        session.commit()
    except IntegrityError:
        # Concurrent upload of the same content
        session.rollback()
        existing = repo.get_by_sha(session, decoded.sha256)
        return UploadResult(filename=filename, status="duplicate", image=to_out(existing, 0) if existing else None)
    log.info("stored training image %s (%dx%d) as %s", image.id, image.width, image.height, key)
    return UploadResult(filename=filename, status="created", image=to_out(image, 0))


@router.post("", response_model=list[UploadResult], summary="Upload one or more training images")
async def upload_images(
    files: Annotated[list[UploadFile], File(description="Image files (JPEG/PNG/WebP/BMP)")],
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> list[UploadResult]:
    results = []
    for f in files:
        data = await read_upload(f)
        try:
            results.append(await run_in_threadpool(store_upload, session, storage, f.filename, data))
        except Exception as exc:  # storage/db failure for one file should not abort the batch
            log.exception("upload of %s failed", f.filename)
            session.rollback()
            results.append(UploadResult(filename=f.filename, status="error", error=f"storage error: {exc}"))
    return results


@router.get("", response_model=ImageList, summary="List training images")
def list_images(
    status_filter: Annotated[Optional[AnnotationStatus], Query(alias="status")] = None,
    split: Optional[DatasetSplit] = None,
    negative: bool = False,
    needs_review: bool = Query(False, description="labeled images not yet checked for all active classes"),
    has_suggestions: bool = Query(False, description="images with open batch-test suggestions"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_db),
) -> ImageList:
    restrict = needs_review_ids(session) if needs_review else None
    if has_suggestions:
        with_suggestions = list(session.execute(select(ImageSuggestion.image_id)).scalars())
        restrict = with_suggestions if restrict is None else sorted(set(restrict) & set(with_suggestions))
    total, items = repo.list_images(session, status_filter, split, negative, restrict, offset, limit)
    counts = repo.annotation_counts(session, [i.id for i in items])
    active = active_class_names(session)
    suggestions = suggestions_for(session, [i.id for i in items])
    out = []
    for i in items:
        o = to_out(i, counts.get(i.id, {}).get("positive", 0), active, counts.get(i.id, {}).get("hard_negative", 0))
        if i.id in suggestions:
            o.suggestion_count = len(suggestions[i.id].detections_json)
        out.append(o)
    return ImageList(total=total, items=out)


@router.get("/stats", summary="Dataset statistics")
def stats(session: Session = Depends(get_db)) -> dict:
    return dataset_stats(session)


@router.get("/{image_id}", response_model=ImageDetail, summary="Image metadata with annotations")
def get_image(image_id: int, session: Session = Depends(get_db)) -> ImageDetail:
    return to_detail(get_image_or_404(session, image_id), active_class_names(session), session)


@router.get("/{image_id}/neighbours", summary="Previous/next image id (optionally within a status)")
def neighbours(
    image_id: int,
    status_filter: Annotated[Optional[AnnotationStatus], Query(alias="status")] = None,
    session: Session = Depends(get_db),
) -> dict:
    prev_id, next_id = repo.neighbour_ids(session, image_id, status_filter)
    return {"previous": prev_id, "next": next_id}


def _stream(storage: ObjectStorage, key: str, fallback_type: str) -> StreamingResponse:
    body, meta = storage.open_stream(storage.settings.bucket_images, key)
    headers = {"Cache-Control": "private, max-age=86400, immutable"}
    if meta.get("content_length"):
        headers["Content-Length"] = str(meta["content_length"])
    return StreamingResponse(body.iter_chunks(256 * 1024), media_type=meta.get("content_type") or fallback_type, headers=headers)


@router.get("/{image_id}/file", summary="Original image file", response_class=Response)
def image_file(image_id: int, session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)):
    image = get_image_or_404(session, image_id)
    return _stream(storage, image.s3_object_key, image.content_type)


@router.get("/{image_id}/thumbnail", summary="JPEG thumbnail", response_class=Response)
def image_thumbnail(image_id: int, session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)):
    image = get_image_or_404(session, image_id)
    return _stream(storage, image.thumbnail_key or image.s3_object_key, "image/jpeg")


@router.patch("/{image_id}", response_model=ImageDetail, summary="Change status or split of an image")
def update_image(image_id: int, body: ImageUpdate, session: Session = Depends(get_db)) -> ImageDetail:
    image = get_image_or_404(session, image_id)
    if body.annotation_status is not None:
        annotation_service.set_status(session, image, AnnotationStatus(body.annotation_status))
    if body.dataset_split is not None:
        # Explicit manual override of the persisted split
        image.dataset_split = DatasetSplit(body.dataset_split)
    session.commit()
    session.refresh(image)
    return to_detail(image, active_class_names(session), session)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an image and its annotations")
def delete_image(image_id: int, session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)) -> Response:
    image = get_image_or_404(session, image_id)
    keys = [image.s3_object_key, image.thumbnail_key]
    session.delete(image)
    session.commit()
    # Existing dataset snapshots contain their own copies, so they stay reproducible.
    for key in filter(None, keys):
        try:
            storage.delete(storage.settings.bucket_images, key)
        except Exception:
            log.exception("could not delete s3 object %s", key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{image_id}/detect", response_model=DetectResponse, summary="Run a model on a stored training image")
def detect_stored_image(
    image_id: int,
    model: Annotated[Optional[str], Form()] = None,
    input_size: Annotated[Optional[str], Form()] = None,
    confidence: Annotated[Optional[float], Form()] = None,
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    registry: ModelRegistry = Depends(get_registry),
) -> DetectResponse:
    image = get_image_or_404(session, image_id)
    data = storage.get_bytes(storage.settings.bucket_images, image.s3_object_key)
    return detect_or_http_error(session, registry, decode_image(data), model, input_size, confidence)
