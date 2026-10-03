"""Import the COCO-pretrained RTMDet-S as a model version (no training).

The 80 COCO classes are merged into the configured classes inside the
exported graph according to each class's COCO sources (score = max over the
source classes). Only active classes WITH a COCO mapping are part of this
model. This gives a usable model before any own training data exists. It
becomes production only if no production model exists yet.
"""
from __future__ import annotations

import json
import logging
import os
import shutil

from sqlalchemy import select

from odcore.classes import coco_index_mapping, list_classes
from odcore.db import ModelStatus, ModelVersion
from odcore.geometry import parse_input_size
from odcore.openvino_detector import OpenVinoDetector
from odcore.settings_store import get_setting

from .config import get_settings
from .dataset import current_validation_set, load_val_samples
from .db import session_factory, storage
from .evaluate import evaluate_detector
from .export_onnx import RTMDetDeployWrapper, build_detector, export_onnx
from .export_openvino import export_openvino, verify_openvino
from .publish import Artifacts, publish_model
from odcore.architectures import DEFAULT_BASE_MODEL, get_base_model

from .rtmdet.base_config import ensure_base_checkpoint, load_base_config

log = logging.getLogger("trainer.bootstrap")


def bootstrap_exists(architecture: str) -> bool:
    with session_factory()() as session:
        return session.execute(
            select(ModelVersion.id).where(ModelVersion.kind == "coco-bootstrap", ModelVersion.architecture == architecture)
        ).first() is not None


def run_bootstrap(force: bool = False, base_id: str = DEFAULT_BASE_MODEL) -> str | None:
    base = get_base_model(base_id)
    if not force and bootstrap_exists(base.architecture):
        log.info("COCO bootstrap model for %s already exists, nothing to do", base.architecture)
        return None
    settings = get_settings()
    s3 = storage()
    with session_factory()() as session:
        mapped = [c for c in list_classes(session, active_only=True) if c.coco_classes]
        mapping = {c.name: list(c.coco_classes) for c in mapped}
        index_mapping = coco_index_mapping(mapped)
        width, height = parse_input_size(get_setting(session, "default_input_size"))
        eval_conf = float(get_setting(session, "eval_confidence"))
        nms_iou = float(get_setting(session, "nms_iou_threshold"))
    if not mapped:
        raise RuntimeError("no active class has a COCO mapping; the COCO model cannot be imported")
    class_names = [c.name for c in mapped]
    groups = [index_mapping[name] for name in class_names]

    work = os.path.join(settings.work_dir, "bootstrap")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    try:
        ckpt = ensure_base_checkpoint(base, os.path.join(settings.work_dir, "base"))
        cfg = load_base_config(base, num_classes=80)
        config_path = os.path.join(work, "config.py")
        cfg.dump(config_path)
        detector = build_detector(cfg, ckpt)
        wrapper = RTMDetDeployWrapper(detector, class_groups=groups)
        onnx_path = os.path.join(work, "model.onnx")
        export_onnx(wrapper, onnx_path, width, height)
        ov_dir = os.path.join(work, "openvino")
        xml_path = export_openvino(onnx_path, ov_dir)
        verification = verify_openvino(wrapper, xml_path, [(width, height)])

        metrics = None
        with session_factory()() as session:
            val_dir = current_validation_set(session, s3, work, class_names)
        if val_dir:
            import openvino as ov

            coco_val, samples = load_val_samples(val_dir)
            metrics = evaluate_detector(OpenVinoDetector(ov.Core(), xml_path, width, height),
                                        coco_val, samples, tuple(class_names), eval_conf, nms_iou)
            metrics["note"] = "evaluated on the validation images labeled at import time"
            metrics["export_verification"] = verification
        metrics_path = os.path.join(work, "metrics.json")
        with open(metrics_path, "w") as f:
            json.dump(metrics or {"export_verification": verification}, f, indent=1)

        mv = publish_model(
            Artifacts(checkpoint_path=None, checkpoint_key=base.checkpoint_key, onnx_path=onnx_path,
                      openvino_dir=ov_dir, config_path=config_path, metrics_path=metrics_path),
            kind="coco-bootstrap",
            architecture=base.architecture,
            input_width=width,
            input_height=height,
            class_names=class_names,
            metrics=metrics,
            training_run_id=None,
            dataset_snapshot=None,
            class_mapping=mapping,
            status=ModelStatus.production,  # only if no production model exists (checked in publish_model)
            notes=f"COCO-pretrained {base.label[:-7]} (MMDetection model zoo, COCO AP {base.coco_ap}), "
                  "COCO classes merged via class mapping; not trained on own data",
        )
        return mv.version
    finally:
        shutil.rmtree(work, ignore_errors=True)
