"""Batch test: run a model over all open images and store the detections as suggestions.

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

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from odcore.db import AnnotationStatus, BatchStatus, Image, ImageSuggestion, PredictionBatch, utcnow
from odcore.geometry import decode_image
from odcore.settings_store import get_setting
from odcore.storage import ObjectStorage

from app.services.dataset import needs_review_ids
from app.services.model_registry import ModelRegistry, resolve_model

log = logging.getLogger(__name__)

SCOPES = ("unlabeled", "unlabeled_and_review")


def select_image_ids(session: Session, scope: str) -> list[int]:
    ids = list(
        session.execute(
            select(Image.id).where(Image.annotation_status == AnnotationStatus.unlabeled).order_by(Image.id)
        ).scalars()
    )
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
        except Exception as exc:
            batch.status, batch.error, batch.finished_at = BatchStatus.failed, str(exc), utcnow()
            session.commit()
            return
        batch.status = BatchStatus.running
        batch.model_version = ref.version
        batch.total = len(image_ids)
        batch.started_at = utcnow()
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

    processed = detections = failed = 0
    for image_id in image_ids:
        with session_factory() as session:
            batch = session.get(PredictionBatch, batch_id)
            if batch.status == BatchStatus.cancelled:
                log.info("batch test #%d cancelled after %d images", batch_id, processed)
                return
            image = session.get(Image, image_id)
            if image is not None:
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
            session.commit()

    with session_factory() as session:
        batch = session.get(PredictionBatch, batch_id)
        if batch.status == BatchStatus.running:
            batch.status = BatchStatus.completed
            batch.finished_at = utcnow()
            session.commit()
    log.info("batch test #%d done: %d images, %d suggestions, %d failed", batch_id, processed, detections, failed)


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
