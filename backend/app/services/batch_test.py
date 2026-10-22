"""Batch test: run a model over all open images and store the detections as suggestions.

With an ``errors_*`` scope it is an *error analysis* instead: the model runs over
labeled images, its detections are matched against the annotations (same rule as
the trainer's precision/recall) and every image with false positives or false
negatives gets an ``ImageErrorMark``. Each analysis replaces all previous marks.

Runs inside the API process on a single background thread (one batch at a
time), using the same compiled OpenVINO models as ``/detect``. Progress is
written to ``prediction_batches``; cancelling sets the status, which the loop
checks before each image. Suggestions do not change annotations; they are
shown as predictions in the annotation UI and removed once the image is saved
as labeled.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from odcore.classes import active_class_names
from odcore.db import AnnotationStatus, BatchStatus, DatasetSplit, Image, ImageErrorMark, ImageSuggestion, PredictionBatch, utcnow
from odcore.geometry import IGNORE_COVERAGE, box_ioa, box_iou, decode_image
from odcore.settings_store import get_setting
from odcore.storage import ObjectStorage

from app.db.repositories.images import last_upload_ids
from app.services.dataset import needs_review_ids
from app.services.duplicates import update_duplicates
from app.services.model_registry import ModelRegistry, resolve_model

log = logging.getLogger(__name__)

SUGGESTION_SCOPES = ("unlabeled", "unlabeled_and_review", "unlabeled_last_upload", "unlabeled_untested")
# error analysis on labeled images: validation split only, or all labeled images
ERROR_SCOPES = ("errors_validation", "errors_labeled")
SCOPES = SUGGESTION_SCOPES + ERROR_SCOPES
MATCH_IOU = 0.5


def _in_ignore_region(det: dict, cls: str, ignore: list[dict] | None) -> bool:
    regions = [r for r in ignore or () if r["class"] == cls]
    if not regions:
        return False
    keys = ("x1", "y1", "x2", "y2")
    box = [[det["bbox"][k] for k in keys]]
    return bool(box_ioa(box, [[r["bbox"][k] for k in keys] for r in regions]).max() >= IGNORE_COVERAGE)


def find_errors(detections: list[dict], annotations: list[dict], iou_thr: float = MATCH_IOU,
                ignore: list[dict] | None = None) -> tuple[int, list[dict], list[dict]]:
    """Greedy one-to-one matching per class, highest confidence first (as the trainer's precision/recall).

    Returns ``(true positives, false positives, false negatives)``; false positives are the
    unmatched detections, false negatives the unmatched annotations. Unmatched detections that lie
    in an ``ignore`` region of their class (same box format as ``annotations``) are no errors.
    """
    tp, fps, fns = 0, [], []
    for cls in sorted({d["class"] for d in detections} | {a["class"] for a in annotations}):
        dets = sorted((d for d in detections if d["class"] == cls), key=lambda d: -d["confidence"])
        gts = [a for a in annotations if a["class"] == cls]
        xyxy = lambda items: np.array([[i["bbox"][k] for k in ("x1", "y1", "x2", "y2")] for i in items]).reshape(-1, 4)  # noqa: E731
        ious = box_iou(xyxy(dets), xyxy(gts)) if dets and gts else np.zeros((len(dets), len(gts)))
        used = np.zeros(len(gts), dtype=bool)
        for i, d in enumerate(dets):
            best, best_j = iou_thr, -1
            for j in range(len(gts)):
                if not used[j] and ious[i, j] >= best:
                    best, best_j = ious[i, j], j
            if best_j >= 0:
                used[best_j] = True
                tp += 1
            elif not _in_ignore_region(d, cls, ignore):
                fps.append(d)
        fns += [g for g, u in zip(gts, used) if not u]
    return tp, fps, fns


def select_image_ids(session: Session, scope: str) -> list[int]:
    if scope in ERROR_SCOPES:
        stmt = select(Image.id).where(Image.annotation_status == AnnotationStatus.labeled, Image.deleted_at.is_(None))
        if scope == "errors_validation":
            stmt = stmt.where(Image.dataset_split == DatasetSplit.validation)
        return list(session.execute(stmt.order_by(Image.id)).scalars())
    ids = list(
        session.execute(
            select(Image.id).where(Image.annotation_status == AnnotationStatus.unlabeled, Image.deleted_at.is_(None))
            .order_by(Image.id)
        ).scalars()
    )
    if scope == "unlabeled_untested":
        # every batch test leaves a suggestion row per image (empty if nothing was found)
        tested = set(session.execute(select(ImageSuggestion.image_id)).scalars())
        return [i for i in ids if i not in tested]
    if scope == "unlabeled_last_upload":
        recent = set(last_upload_ids(session))
        return [i for i in ids if i in recent]
    if scope == "unlabeled_and_review":
        ids += needs_review_ids(session)
    return sorted(set(ids))


def run_batch(batch_id: int, session_factory: sessionmaker[Session], storage: ObjectStorage, registry: ModelRegistry) -> None:
    """Process one batch synchronously (called on the background thread, or directly in tests)."""
    with session_factory() as session:
        batch = session.get(PredictionBatch, batch_id)
        if batch is None or batch.status != BatchStatus.queued:
            return
        try:
            ref = resolve_model(session, batch.model_ref)
            iou = float(get_setting(session, "nms_iou_threshold"))
            image_ids = select_image_ids(session, batch.scope)
            active = set(active_class_names(session))
        except Exception as exc:
            batch.status, batch.error, batch.finished_at = BatchStatus.failed, str(exc), utcnow()
            session.commit()
            return
        batch.status = BatchStatus.running
        batch.model_version = ref.version
        batch.total = len(image_ids)
        batch.started_at = utcnow()
        analysis = batch.scope in ERROR_SCOPES
        if analysis:
            session.execute(delete(ImageErrorMark))  # marks always describe the latest analysis
        session.commit()
        width, height, conf = batch.input_width, batch.input_height, batch.confidence
    log.info("batch test #%d: %s on %d images", batch_id, ref.version, len(image_ids))

    try:
        detector = registry.get_detector(ref, width, height)
    except Exception as exc:
        log.exception("batch test #%d: model could not be loaded", batch_id)
        with session_factory() as session:
            batch = session.get(PredictionBatch, batch_id)
            batch.status, batch.error, batch.finished_at = BatchStatus.failed, f"model could not be loaded: {exc}", utcnow()
            session.commit()
        return

    processed = detections = failed = marked = 0
    for image_id in image_ids:
        with session_factory() as session:
            batch = session.get(PredictionBatch, batch_id)
            if batch.status == BatchStatus.cancelled:
                log.info("batch test #%d cancelled after %d images", batch_id, processed)
                return
            image = session.get(Image, image_id)
            if image is not None and image.deleted_at is None:
                try:
                    data = storage.get_bytes(storage.settings.bucket_images, image.s3_object_key)
                    result = detector.detect(decode_image(data), conf, iou)
                    dets = [
                        {
                            "class": ref.class_names[d.class_id],
                            "confidence": round(d.confidence, 4),
                            "bbox": {"x1": round(d.x1), "y1": round(d.y1), "x2": round(d.x2), "y2": round(d.y2)},
                        }
                        for d in result.detections
                    ]
                    if analysis:
                        n = _store_error_mark(session, image, dets, ref.class_names, active, batch_id, ref.version, width, height, conf)
                        detections += n
                        if n:
                            marked += 1
                    else:
                        session.execute(delete(ImageSuggestion).where(ImageSuggestion.image_id == image_id))
                        session.add(ImageSuggestion(
                            image_id=image_id, batch_id=batch_id, model_version=ref.version, input_width=width,
                            input_height=height, confidence=conf, detections_json=dets,
                        ))
                        detections += len(dets)
                except Exception as exc:  # one broken image must not stop the batch
                    log.warning("batch test #%d: image %d failed: %s", batch_id, image_id, exc)
                    failed += 1
                    batch.error = f"image {image_id}: {exc}"
            processed += 1
            batch.processed, batch.detections, batch.failed_images = processed, detections, failed
            batch.marked_images = marked
            session.commit()

    with session_factory() as session:
        batch = session.get(PredictionBatch, batch_id)
        if batch.status == BatchStatus.running:
            batch.status = BatchStatus.completed
            batch.finished_at = utcnow()
            session.commit()
    log.info("batch test #%d done: %d images, %d suggestions, %d failed", batch_id, processed, detections, failed)
    if not analysis:
        # open images without suggestions are now known to be empty: check them for duplicates
        try:
            with session_factory() as session:
                update_duplicates(session, storage)
        except Exception:
            log.exception("duplicate check after batch test #%d failed", batch_id)


def _store_error_mark(session: Session, image: Image, dets: list[dict], model_classes: tuple[str, ...], active: set[str],
                      batch_id: int, version: str, width: int, height: int, conf: float) -> int:
    """Compare detections with the annotations; store a mark if they disagree. Returns the number of errors.

    Only classes the model knows, that are active and that the image was reviewed for are compared
    (an image not yet checked for a class may contain unlabeled objects of it).
    """
    classes = set(model_classes) & active & set(image.reviewed_classes or ())
    gts = [
        {"class": a.class_name, "bbox": {"x1": a.x1, "y1": a.y1, "x2": a.x2, "y2": a.y2}}
        for a in image.annotations if a.type == "positive" and a.class_name in classes
    ]
    ignore = [
        {"class": a.class_name, "bbox": {"x1": a.x1, "y1": a.y1, "x2": a.x2, "y2": a.y2}}
        for a in image.annotations if a.type == "ignore" and a.class_name in classes
    ]
    tp, fps, fns = find_errors([d for d in dets if d["class"] in classes], gts, ignore=ignore)
    session.execute(delete(ImageErrorMark).where(ImageErrorMark.image_id == image.id))
    if fps or fns:
        session.add(ImageErrorMark(
            image_id=image.id, batch_id=batch_id, model_version=version, input_width=width, input_height=height,
            confidence=conf, true_positives=tp, false_positives_json=fps, false_negatives_json=fns,
        ))
    return len(fps) + len(fns)


class BatchRunner:
    """Single background thread; batches are processed one after another."""

    def __init__(self, job: Callable[[int], None]):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="batch-test")
        self._job = job
        self._lock = threading.Lock()

    def submit(self, batch_id: int) -> None:
        with self._lock:
            self._executor.submit(self._safe, batch_id)

    def _safe(self, batch_id: int) -> None:
        try:
            self._job(batch_id)
        except Exception:
            log.exception("batch test #%d crashed", batch_id)


_runner: BatchRunner | None = None


def get_runner() -> BatchRunner:
    global _runner
    if _runner is None:
        from app.core.database import get_sessionmaker
        from app.core.s3 import get_storage
        from app.services.model_registry import get_registry

        _runner = BatchRunner(lambda batch_id: run_batch(batch_id, get_sessionmaker(), get_storage(), get_registry()))
    return _runner


def fail_interrupted_batches(session: Session) -> int:
    """On API start: batches that were queued/running in a previous process cannot continue."""
    rows = session.execute(
        select(PredictionBatch).where(PredictionBatch.status.in_([BatchStatus.queued, BatchStatus.running]))
    ).scalars().all()
    for b in rows:
        b.status, b.error, b.finished_at = BatchStatus.failed, "interrupted by API restart", utcnow()
    session.commit()
    return len(rows)
