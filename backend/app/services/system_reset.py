"""Reset the training system to its initial state ("System zurücksetzen" in the settings).

Deletes all images (with annotations, suggestions, error marks, tombstones), all training runs with their dataset
snapshots, batch tests and benchmarks and all custom models, and restores the default classes. COCO bootstrap
models whose classes are all default classes are kept; if none of them is production afterwards, the newest one
becomes production, or - without any - a new bootstrap import is queued. Settings (incl. the connections to the
production system and the client annotator) are kept, as are backups and everything on remote systems.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from odcore.architectures import DEFAULT_BASE_MODEL
from odcore.classes import DEFAULT_CLASSES
from odcore.db import (Annotation, BatchStatus, DeletedImage, DetectionClass, Image, ImageErrorMark, ImageSuggestion,
                       ModelBenchmark, ModelStatus, ModelVersion, PredictionBatch, SnapshotImage, TrainingRun,
                       TrainingStatus, utcnow)
from odcore.storage import ObjectStorage

from app.services.model_registry import ModelRegistry

log = logging.getLogger(__name__)

CONFIRM_WORD = "reset"


class ResetBlockedError(RuntimeError):
    pass


def blocking_jobs(session: Session, backup_dir: Optional[str]) -> list[str]:
    """Jobs that would work on data the reset deletes."""
    reasons = []
    active = [TrainingStatus.queued, TrainingStatus.running]
    if n := session.scalar(select(func.count(TrainingRun.id)).where(TrainingRun.status.in_(active))):
        reasons.append(f"{n} training run(s) queued or running")
    jobs = [BatchStatus.queued, BatchStatus.running]
    if n := session.scalar(select(func.count(PredictionBatch.id)).where(PredictionBatch.status.in_(jobs))):
        reasons.append(f"{n} batch test(s) queued or running")
    if n := session.scalar(select(func.count(ModelBenchmark.id)).where(ModelBenchmark.status.in_(jobs))):
        reasons.append(f"{n} benchmark(s) queued or running")
    if backup_dir and os.path.isdir(backup_dir):
        from odbackup.core import is_busy

        if is_busy(backup_dir):
            reasons.append("a backup or restore is running")
    return reasons


def is_kept(mv: ModelVersion, default_names: set[str]) -> bool:
    """COCO bootstrap models that only detect default classes stay; trained models are custom."""
    return mv.kind == "coco-bootstrap" and set(mv.class_names) <= default_names


def preview(session: Session) -> dict[str, Any]:
    default_names = {c["name"] for c in DEFAULT_CLASSES}
    models = list(session.scalars(select(ModelVersion).order_by(ModelVersion.id)))
    return {
        "images": session.scalar(select(func.count(Image.id))) or 0,
        "annotations": session.scalar(select(func.count(Annotation.id))) or 0,
        "training_runs": session.scalar(select(func.count(TrainingRun.id))) or 0,
        "models_deleted": [m.version for m in models if not is_kept(m, default_names)],
        "models_kept": [m.version for m in models if is_kept(m, default_names)],
        "classes": [c["name"] for c in DEFAULT_CLASSES],
    }


def reset_system(session: Session, storage: ObjectStorage, registry: ModelRegistry, backup_dir: Optional[str]) -> dict[str, Any]:
    if reasons := blocking_jobs(session, backup_dir):
        raise ResetBlockedError("system reset not possible: " + "; ".join(reasons))
    summary = preview(session)
    deleted_versions = summary["models_deleted"]

    # -- database: one transaction ------------------------------------------------------------
    session.execute(delete(SnapshotImage))
    session.execute(delete(ImageSuggestion))
    session.execute(delete(ImageErrorMark))
    session.execute(delete(Annotation))
    session.execute(update(Image).values(duplicate_of=None))
    session.execute(delete(Image))
    session.execute(delete(DeletedImage))  # the same images may be uploaded again
    session.execute(update(ModelVersion).values(training_run_id=None))
    session.execute(update(TrainingRun).values(model_version_id=None))
    session.execute(delete(TrainingRun))
    session.execute(delete(PredictionBatch))
    session.execute(delete(ModelBenchmark))
    if deleted_versions:
        session.execute(delete(ModelVersion).where(ModelVersion.version.in_(deleted_versions)))
    session.execute(delete(DetectionClass))
    session.add_all(DetectionClass(sort_order=i, active=True, **c) for i, c in enumerate(DEFAULT_CLASSES))
    session.flush()

    production = session.scalar(select(ModelVersion).where(ModelVersion.status == ModelStatus.production))
    if production is None:
        newest = session.scalar(select(ModelVersion).order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc()))
        if newest is not None:
            newest.status = ModelStatus.production
            newest.activated_at = utcnow()
            production = newest
    session.commit()
    summary["production_model"] = production.version if production else None
    log.warning("system reset: %d images, %d training runs and models %s deleted, classes reset to defaults",
                summary["images"], summary["training_runs"], deleted_versions or "-")

    # -- files: the rows are gone first; if S3 fails, only unreferenced files remain ----------------
    warnings: list[str] = []
    buckets = storage.settings
    for bucket, prefixes in ((buckets.bucket_images, [""]), (buckets.bucket_datasets, [""]),
                             (buckets.bucket_models, [f"{v}/" for v in deleted_versions])):
        for prefix in prefixes:
            try:
                storage.delete_prefix(bucket, prefix)
            except Exception as exc:
                log.exception("system reset: could not delete s3://%s/%s", bucket, prefix)
                warnings.append(f"files in s3://{bucket}/{prefix} could not be deleted: {exc.__class__.__name__}")
    for version in deleted_versions:
        registry.forget(version)

    summary["bootstrap_queued"] = False
    if production is None:  # like a fresh installation: import the COCO model again
        from app.core.queue import enqueue_bootstrap

        try:
            enqueue_bootstrap(False, DEFAULT_BASE_MODEL)
            summary["bootstrap_queued"] = True
        except Exception as exc:
            warnings.append(f"COCO model import could not be queued ({exc.__class__.__name__}): start it on the Models page")
    summary["warnings"] = warnings
    return summary
