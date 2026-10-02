"""Upload model artifacts and register an immutable model version."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from odcore.db import ModelStatus, ModelVersion, format_version, parse_version_number, utcnow

from .db import session_factory, storage

log = logging.getLogger(__name__)


@dataclass
class Artifacts:
    checkpoint_path: Optional[str]   # None -> reuse ``checkpoint_key`` (e.g. base checkpoint)
    onnx_path: str
    openvino_dir: str
    config_path: Optional[str]
    metrics_path: Optional[str] = None
    checkpoint_key: Optional[str] = None


def next_version() -> str:
    with session_factory()() as session:
        versions = session.execute(select(ModelVersion.version)).scalars().all()
    numbers = [parse_version_number(v) for v in versions]
    return format_version(max(numbers, default=0) + 1)


def publish_model(artifacts: Artifacts, *, kind: str, input_width: int, input_height: int, class_names: list[str],
                  metrics: dict | None, training_run_id: int | None, dataset_snapshot: str | None,
                  class_mapping: dict | None = None, status: ModelStatus = ModelStatus.candidate,
                  notes: str | None = None) -> ModelVersion:
    """Upload artifacts to ``s3://models/<version>/`` and insert the DB row.

    New versions are always candidates unless explicitly requested otherwise
    (only the initial COCO bootstrap may become production when none exists).
    """
    s3 = storage()
    bucket = s3.settings.bucket_models
    for attempt in range(5):
        version = next_version()
        prefix = f"{version}/"
        keys: dict[str, Any] = {}
        if artifacts.checkpoint_path:
            keys["checkpoint_key"] = prefix + "checkpoint.pth"
            s3.upload_file(bucket, keys["checkpoint_key"], artifacts.checkpoint_path, "application/octet-stream")
        else:
            keys["checkpoint_key"] = artifacts.checkpoint_key
        keys["onnx_key"] = prefix + "model.onnx"
        s3.upload_file(bucket, keys["onnx_key"], artifacts.onnx_path, "application/octet-stream")
        keys["openvino_key"] = prefix + "openvino/model.xml"
        s3.upload_file(bucket, keys["openvino_key"], os.path.join(artifacts.openvino_dir, "model.xml"), "application/xml")
        s3.upload_file(bucket, prefix + "openvino/model.bin", os.path.join(artifacts.openvino_dir, "model.bin"), "application/octet-stream")
        keys["config_key"] = None
        if artifacts.config_path:
            keys["config_key"] = prefix + "config.py"
            s3.upload_file(bucket, keys["config_key"], artifacts.config_path, "text/x-python")
        if artifacts.metrics_path:
            s3.upload_file(bucket, prefix + "metrics.json", artifacts.metrics_path, "application/json")

        with session_factory()() as session:
            if status == ModelStatus.production:
                existing = session.execute(select(ModelVersion).where(ModelVersion.status == ModelStatus.production)).scalars().first()
                if existing is not None:
                    status = ModelStatus.candidate
            mv = ModelVersion(
                version=version,
                status=status,
                kind=kind,
                architecture="rtmdet-s",
                input_width=input_width,
                input_height=input_height,
                class_names=list(class_names),
                class_mapping_json=class_mapping,
                metrics_json=metrics,
                dataset_snapshot=dataset_snapshot,
                training_run_id=training_run_id,
                notes=notes,
                **keys,
            )
            if status == ModelStatus.production:
                mv.activated_at = utcnow()
            session.add(mv)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                log.warning("version %s was taken concurrently, retrying", version)
                continue
            session.refresh(mv)
            log.info("registered model %s (%s, status %s)", mv.version, kind, mv.status.value)
            return mv
    raise RuntimeError("could not allocate a model version")
