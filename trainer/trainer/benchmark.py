"""Benchmark: every model version on the *current* validation set, with the training evaluation protocol.

Metrics stored with each model describe its validation set at training time, which grows over time, so
they are not comparable between models. The benchmark evaluates all non-archived model versions (production and
candidates; exported OpenVINO models, each at its own input size) on today's labeled validation images and their hard negatives.
The split is persistent, but it can be changed by hand (e.g. real intrusions moved to validation): for each
model the number of current validation images it was *trained* on is reported (``seen_in_training``, from its
snapshot manifest) - such a model looks better than it is on those images.
"""
from __future__ import annotations

import json
import logging
import os
import shutil

from sqlalchemy import select

from odcore.classes import active_class_names
from odcore.db import BatchStatus, ModelBenchmark, ModelStatus, ModelVersion, utcnow
from odcore.openvino_detector import OpenVinoDetector
from odcore.settings_store import get_setting

from .config import get_settings
from .dataset import current_validation_set, load_hard_negatives, load_val_samples
from .db import session_factory, storage
from .evaluate import evaluate_detector, num_boxes

log = logging.getLogger(__name__)


def _update(benchmark_id: int, **fields) -> None:
    with session_factory()() as session:
        b = session.get(ModelBenchmark, benchmark_id)
        for k, v in fields.items():
            setattr(b, k, v)
        session.commit()


def _seen_in_training(s3, run_id: int | None, val_ids: set[int], work: str) -> int | None:
    """How many of the current validation images were training images of this model (None = unknown)."""
    if run_id is None:
        return 0  # imported model (COCO bootstrap): not trained on own images
    path = os.path.join(work, f"manifest-{run_id}.json")
    try:
        s3.download_file(s3.settings.bucket_datasets, f"{run_id}/manifest.json", path)
        with open(path) as f:
            manifest = json.load(f)
    except Exception:  # snapshot released or unreadable
        return None
    return sum(1 for im in manifest.get("images", []) if im.get("split") == "train" and im.get("id") in val_ids)


def run_benchmark(benchmark_id: int) -> None:
    import openvino as ov

    s3 = storage()
    work = os.path.join(get_settings().work_dir, f"benchmark-{benchmark_id}")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    try:
        with session_factory()() as session:
            b = session.get(ModelBenchmark, benchmark_id)
            if b is None or b.status != BatchStatus.queued:
                return
            class_names = active_class_names(session)
            eval_conf = float(get_setting(session, "eval_confidence"))
            nms_iou = float(get_setting(session, "nms_iou_threshold"))
            # archived versions are skipped: they are out of the race and each model costs a full evaluation
            models = [
                (m.version, m.status.value, m.openvino_key, tuple(m.class_names), m.input_width, m.input_height, m.training_run_id)
                for m in session.execute(
                    select(ModelVersion).where(ModelVersion.status != ModelStatus.archived).order_by(ModelVersion.id)
                ).scalars() if m.openvino_key
            ]
            val_dir = current_validation_set(session, s3, work, class_names)
        if not val_dir:
            raise RuntimeError(f"no labeled validation images checked for all active classes {class_names}")
        coco_val, samples = load_val_samples(val_dir)
        hard_negatives = load_hard_negatives(val_dir)
        _update(benchmark_id, status=BatchStatus.running, started_at=utcnow(), class_names=class_names,
                num_images=len(samples), num_boxes=num_boxes(coco_val),
                num_hard_negatives=len(hard_negatives), total=len(models), processed=0, results_json={})
        log.info("benchmark #%d: %d models on %d validation images", benchmark_id, len(models), len(samples))

        results: dict = {}
        core = ov.Core()
        val_ids = {s["id"] for s in samples}
        for n, (version, status, xml_key, model_classes, width, height, run_id) in enumerate(models, start=1):
            try:
                target = os.path.join(work, version)
                s3.download_file(s3.settings.bucket_models, xml_key, os.path.join(target, "model.xml"))
                s3.download_file(s3.settings.bucket_models, xml_key[: -len(".xml")] + ".bin", os.path.join(target, "model.bin"))
                detector = OpenVinoDetector(core, os.path.join(target, "model.xml"), width, height)
                metrics = evaluate_detector(detector, coco_val, samples, model_classes, eval_conf, nms_iou,
                                            hard_negatives=hard_negatives, image_dir=os.path.join(val_dir, "images"))
                metrics["status"] = status
                metrics["seen_in_training"] = _seen_in_training(s3, run_id, val_ids, work)
                results[version] = metrics
            except Exception as exc:  # one broken model must not stop the benchmark
                log.exception("benchmark #%d: %s failed", benchmark_id, version)
                results[version] = {"status": status, "error": str(exc)}
            _update(benchmark_id, processed=n, results_json=dict(results))
            shutil.rmtree(os.path.join(work, version), ignore_errors=True)
        _update(benchmark_id, status=BatchStatus.completed, finished_at=utcnow())
    except Exception as exc:
        log.exception("benchmark #%d failed", benchmark_id)
        _update(benchmark_id, status=BatchStatus.failed, error=str(exc), finished_at=utcnow())
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
