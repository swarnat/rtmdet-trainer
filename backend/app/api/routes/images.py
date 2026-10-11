from __future__ import annotations

import logging
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from odcore.classes import active_class_names, is_reviewed_for
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from odcore.db import AnnotationStatus, DatasetSplit, DeletedImage, Image, ImageErrorMark, ImageSuggestion, utcnow
from odcore.geometry import decode_image
from odcore.storage import ObjectStorage

from app.api.deps import read_upload
from app.api.routes.detect import detect_or_http_error
from app.core.database import get_db
from app.core.s3 import get_storage
from app.db.repositories import images as repo
from app.schemas.annotation import (AnnotationOut, CameraGroup, CameraGroupImage, CameraGroups, DuplicateGroup, DuplicateResolve, ImageDetail, ImageList, ImageOut, ImageUpdate,
                                    UploadResult, UrlDownload)
from app.schemas.batch_test import ErrorMarkOut, SuggestionOut
from app.schemas.detection import DetectResponse
from app.services import annotation as annotation_service
from app.services import duplicates
from app.services.camera_groups import open_without_suggestions_groups
from app.services.camera_meta import camera_key
from app.services.dataset import dataset_stats, needs_review_ids
from app.services.model_registry import ModelRegistry, get_registry
from app.services.preprocessing import decode_upload, make_thumbnail
from app.services.url_download import DownloadError, download_image, filename_from_url

log = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["training images"])


def get_image_or_404(session: Session, image_id: int) -> Image:
    image = session.get(Image, image_id)
    if image is None or image.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"image {image_id} not found")
    return image


def to_out(image: Image, count: int, active: list[str] | None = None, hard_negatives: int = 0) -> ImageOut:
    out = ImageOut.model_validate(image)
    out.annotation_status = image.annotation_status.value
    out.dataset_split = image.dataset_split.value if image.dataset_split else None
    out.annotation_count = count
    out.duplicate_of = image.duplicate_of
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


def error_marks_for(session: Session, image_ids: list[int]) -> dict[int, ImageErrorMark]:
    if not image_ids:
        return {}
    rows = session.execute(select(ImageErrorMark).where(ImageErrorMark.image_id.in_(image_ids))).scalars()
    return {m.image_id: m for m in rows}


def set_error_counts(out: ImageOut, mark: Optional[ImageErrorMark]) -> None:
    if mark is not None:
        out.error_fp, out.error_fn = len(mark.false_positives_json), len(mark.false_negatives_json)


def to_detail(image: Image, active: list[str], session: Session) -> ImageDetail:
    positives = sum(1 for a in image.annotations if a.type == "positive")
    base = to_out(image, positives, active, len(image.annotations) - positives)
    suggestion = suggestions_for(session, [image.id]).get(image.id)
    base.suggestion_count = len(suggestion.detections_json) if suggestion else None
    mark = error_marks_for(session, [image.id]).get(image.id)
    set_error_counts(base, mark)
    return ImageDetail(
        **base.model_dump(),
        annotations=[AnnotationOut.model_validate(a) for a in image.annotations],
        suggestion=SuggestionOut.model_validate(suggestion) if suggestion else None,
        error_mark=ErrorMarkOut.model_validate(mark) if mark else None,
    )


def store_upload(session: Session, storage: ObjectStorage, filename: Optional[str], data: bytes) -> UploadResult:
    try:
        decoded = decode_upload(data)
    except ValueError as exc:
        return UploadResult(filename=filename, status="error", error=str(exc))

    existing = repo.get_by_sha(session, decoded.sha256)
    if session.get(DeletedImage, decoded.sha256) is not None or (existing is not None and existing.deleted_at is not None):
        # deleted earlier (tombstone): a repeated upload/batch download must not bring it back
        return UploadResult(filename=filename, status="deleted", error="this image was deleted earlier")
    if existing is not None:
        return UploadResult(filename=filename, status="duplicate", image=to_out(existing, sum(1 for a in existing.annotations if a.type == "positive")))

    bucket = storage.settings.bucket_images
    key = f"images/{decoded.sha256[:2]}/{decoded.sha256}{decoded.extension}"
    thumb_key = f"thumbnails/{decoded.sha256[:2]}/{decoded.sha256}.jpg"
    storage.put_bytes(bucket, key, decoded.data, decoded.content_type)
    thumbnail = make_thumbnail(decoded.image)
    storage.put_bytes(bucket, thumb_key, thumbnail, "image/jpeg")

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
        fingerprint=duplicates.fingerprint(thumbnail),
        camera_key=camera_key(decoded.data),
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


@router.post(
    "/from-url",
    response_model=UploadResult,
    summary="Download a training image from a URL",
    description="Used by the batch download: the client sends one request per URL and shows the progress. "
    "Download/format errors are reported as status=error (HTTP 200) like failed files of a regular upload.",
)
def download_from_url(
    body: UrlDownload,
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadResult:
    url = body.url.strip()
    filename = filename_from_url(url)
    try:
        data = download_image(url)
    except DownloadError as exc:
        return UploadResult(filename=filename, status="error", error=str(exc))
    try:
        return store_upload(session, storage, filename, data)
    except Exception as exc:
        log.exception("storing %s failed", url)
        session.rollback()
        return UploadResult(filename=filename, status="error", error=f"storage error: {exc}")


@router.get("", response_model=ImageList, summary="List training images")
def list_images(
    status_filter: Annotated[Optional[AnnotationStatus], Query(alias="status")] = None,
    split: Optional[DatasetSplit] = None,
    negative: bool = False,
    needs_review: bool = Query(False, description="labeled images not yet checked for all active classes"),
    has_suggestions: bool = Query(False, description="images with open batch-test suggestions"),
    has_errors: bool = Query(False, description="images marked by the latest error analysis (false positives/negatives)"),
    duplicate: bool = Query(False, description="empty images marked as duplicates of another empty image"),
    no_suggestions: bool = Query(False, description="exclude images with batch-test suggestions (no test yet or nothing found)"),
    suggestion_level: Optional[Literal["high", "medium", "low"]] = Query(
        None, description="images with suggestions whose lowest confidence is >= 0.7 (high), 0.4-0.7 (medium) or < 0.4 (low)"
    ),
    last_upload: bool = Query(False, description="images of the most recent upload session (pauses < 30 min)"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_db),
) -> ImageList:
    restrict = needs_review_ids(session) if needs_review else None
    if has_suggestions:
        with_suggestions = list(session.execute(select(ImageSuggestion.image_id)).scalars())
        restrict = with_suggestions if restrict is None else sorted(set(restrict) & set(with_suggestions))
    if last_upload:
        recent = repo.last_upload_ids(session)
        restrict = recent if restrict is None else sorted(set(restrict) & set(recent))
    if suggestion_level:
        level_ids = repo.ids_with_suggestion_level(session, suggestion_level)
        restrict = level_ids if restrict is None else sorted(set(restrict) & set(level_ids))
    if has_errors:
        marked = repo.error_marked_ids(session)
        restrict = marked if restrict is None else sorted(set(restrict) & set(marked))
    exclude = repo.ids_with_suggestions(session) if no_suggestions else None
    total, items = repo.list_images(session, status_filter, split, negative, restrict, duplicate, exclude, offset, limit)
    counts = repo.annotation_counts(session, [i.id for i in items])
    active = active_class_names(session)
    suggestions = suggestions_for(session, [i.id for i in items])
    marks = error_marks_for(session, [i.id for i in items])
    out = []
    for i in items:
        o = to_out(i, counts.get(i.id, {}).get("positive", 0), active, counts.get(i.id, {}).get("hard_negative", 0))
        if i.id in suggestions:
            o.suggestion_count = len(suggestions[i.id].detections_json)
        set_error_counts(o, marks.get(i.id))
        out.append(o)
    return ImageList(total=total, items=out)


@router.post(
    "/duplicates/check",
    summary="Check empty images for duplicates",
    description="Compares all images without objects (labeled negatives and open images whose latest batch test "
    "found nothing) and marks visually identical ones (duplicate_of). Images with annotations or suggestions are "
    "never marked, nor are images kept on the duplicates page. Recomputes all marks; also runs automatically after "
    "every batch test. Strictness: setting duplicate_max_difference.",
)
def check_duplicates(session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)) -> dict:
    return duplicates.update_duplicates(session, storage)


@router.get("/duplicates/groups", response_model=list[DuplicateGroup], summary="Duplicate groups for review")
def duplicate_groups(session: Session = Depends(get_db)) -> list[DuplicateGroup]:
    dups = list(session.execute(
        select(Image).where(Image.duplicate_of.is_not(None), Image.deleted_at.is_(None)).order_by(Image.id)
    ).scalars())
    by_original: dict[int, list[Image]] = {}
    for d in dups:
        by_original.setdefault(d.duplicate_of, []).append(d)
    originals = {i.id: i for i in session.execute(select(Image).where(Image.id.in_(by_original))).scalars()}
    counts = repo.annotation_counts(session, list(originals))
    groups = [
        DuplicateGroup(
            original=to_out(originals[oid], counts.get(oid, {}).get("positive", 0), None, counts.get(oid, {}).get("hard_negative", 0)),
            duplicates=[to_out(d, 0) for d in items],
        )
        for oid, items in by_original.items() if oid in originals
    ]
    return sorted(groups, key=lambda g: (-len(g.duplicates), g.original.id))


@router.post(
    "/duplicates/resolve",
    summary="Apply review decisions of the duplicates page",
    description="keep: the image is no duplicate and is never marked again. delete: like deleting each image "
    "(images used by training snapshots are only hidden).",
)
def resolve_duplicates(body: DuplicateResolve, session: Session = Depends(get_db),
                       storage: ObjectStorage = Depends(get_storage)) -> dict:
    if set(body.keep) & set(body.delete):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "an image cannot be kept and deleted")
    duplicates.keep_images(session, body.keep)
    session.commit()
    deleted = 0
    for image_id in body.delete:
        image = session.get(Image, image_id)
        if image is not None and image.deleted_at is None:
            remove_image(session, storage, image_id)
            deleted += 1
    return {"kept": len(body.keep), "deleted": deleted}


@router.get(
    "/camera-groups",
    response_model=CameraGroups,
    summary="Open images on which a batch test found nothing, grouped by camera, for the quick review",
    description="Only tested images (untested open images are counted in `untested`: run a batch test first). "
    "Ordered so that consecutive images are as similar as possible; compare_with = most similar labeled negative "
    "of the same view and lighting, else the previous image.",
)
def camera_groups(session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)) -> CameraGroups:
    groups, untested = open_without_suggestions_groups(session, storage)
    ids = {e["id"] for g in groups for e in g["images"]} | {e["compare_with"] for g in groups for e in g["images"] if e["compare_with"]}
    images = {i.id: i for i in session.execute(select(Image).where(Image.id.in_(ids))).scalars()}
    return CameraGroups(untested=untested, groups=[
        CameraGroup(camera=g["camera"], images=[
            CameraGroupImage(image=to_out(images[e["id"]], 0), compare_with=e["compare_with"], compare_kind=e["compare_kind"])
            for e in g["images"]
        ])
        for g in groups
    ])


@router.get("/stats", summary="Dataset statistics")
def stats(session: Session = Depends(get_db)) -> dict:
    return dataset_stats(session)


@router.get("/{image_id}", response_model=ImageDetail, summary="Image metadata with annotations")
def get_image(image_id: int, session: Session = Depends(get_db)) -> ImageDetail:
    return to_detail(get_image_or_404(session, image_id), active_class_names(session), session)


@router.get("/{image_id}/neighbours", summary="Previous/next image id (optionally within a status and/or split)")
def neighbours(
    image_id: int,
    status_filter: Annotated[Optional[AnnotationStatus], Query(alias="status")] = None,
    split: Optional[DatasetSplit] = None,
    has_errors: bool = False,
    duplicate: bool = False,
    no_suggestions: bool = False,
    suggestion_level: Optional[Literal["high", "medium", "low"]] = None,
    last_upload: bool = False,
    session: Session = Depends(get_db),
) -> dict:
    exclude = repo.ids_with_suggestions(session) if no_suggestions else None
    only = repo.ids_with_suggestion_level(session, suggestion_level) if suggestion_level else None
    if last_upload:
        recent = repo.last_upload_ids(session)
        only = recent if only is None else sorted(set(only) & set(recent))
    prev_id, next_id = repo.neighbour_ids(session, image_id, status_filter, split, has_errors, duplicate, exclude, only)
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


@router.delete(
    "/{image_id}/error-mark",
    response_model=ImageDetail,
    summary="Remove the error-analysis mark of an image",
    description="For images where the model is wrong but the annotations are right. Saving the image as labeled "
    "removes the mark as well.",
)
def delete_error_mark(image_id: int, session: Session = Depends(get_db)) -> ImageDetail:
    image = get_image_or_404(session, image_id)
    session.execute(sa_delete(ImageErrorMark).where(ImageErrorMark.image_id == image_id))
    session.commit()
    return to_detail(image, active_class_names(session), session)


@router.delete(
    "/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an image and its annotations",
    description="If training snapshots still use the image (snapshot_refs > 0), it is only hidden and its file is kept "
    "until the last of these snapshots is released (failed run or deleted model). Its content hash is remembered: "
    "uploading the same file again is rejected (status 'deleted').",
)
def delete_image(image_id: int, session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)) -> Response:
    get_image_or_404(session, image_id)
    remove_image(session, storage, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def remove_image(session: Session, storage: ObjectStorage, image_id: int) -> None:
    # row lock: a training run that is linking this image right now finishes first
    image = session.get(Image, image_id, with_for_update=True, populate_existing=True)
    # tombstone: uploading the same file again is rejected
    if session.get(DeletedImage, image.sha256) is None:
        session.add(DeletedImage(sha256=image.sha256, original_filename=image.original_filename))
    if image.snapshot_refs > 0:
        image.deleted_at = utcnow()
        image.annotations.clear()  # the snapshots keep their own frozen annotations
        session.execute(sa_delete(ImageSuggestion).where(ImageSuggestion.image_id == image_id))
        session.execute(sa_delete(ImageErrorMark).where(ImageErrorMark.image_id == image_id))
        image.annotation_status = AnnotationStatus.unlabeled
        image.reviewed_classes = None
        image.labeled_at = None
        duplicates.clear_marks_for(session, image)
        session.commit()
        log.info("image %s hidden; file kept for %d training snapshot(s)", image_id, image.snapshot_refs)
        return
    keys = [image.s3_object_key, image.thumbnail_key]
    session.delete(image)
    session.commit()
    for key in filter(None, keys):
        try:
            storage.delete(storage.settings.bucket_images, key)
        except Exception:
            log.exception("could not delete s3 object %s", key)


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
