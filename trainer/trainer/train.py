"""One complete training run: snapshot -> RTMDet training -> export -> evaluation -> registry."""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import traceback

import torch

from odcore.classes import COCO_CLASSES, coco_index_mapping, list_classes
from odcore.db import ModelStatus, ModelVersion, TrainingRun, TrainingStatus, utcnow
from odcore.openvino_detector import OpenVinoDetector
from odcore.settings_store import get_setting

from .config import get_settings
from .dataset import create_snapshot, load_hard_negatives, load_val_samples
from .db import session_factory, storage
from .evaluate import compare, evaluate_detector
from .export_onnx import RTMDetDeployWrapper, build_detector, export_onnx
from .export_openvino import export_openvino, verify_openvino
from .progress import ProgressHookFactory, RunReporter
from .publish import Artifacts, publish_model
from odcore.architectures import base_model_for_architecture, get_base_model

from .rtmdet.base_config import build_init_checkpoint, ensure_base_checkpoint
from .rtmdet.dataset_config import TrainParams, build_config, default_learning_rate

log = logging.getLogger("trainer.train")


def _update_run(run_id: int, **values) -> None:
    with session_factory()() as session:
        run = session.get(TrainingRun, run_id)
        for k, v in values.items():
            setattr(run, k, v)
        session.commit()


def _find_best_checkpoint(work_dir: str) -> str:
    best = sorted(glob.glob(os.path.join(work_dir, "best_coco_bbox_mAP_epoch_*.pth")), key=os.path.getmtime)
    if best:
        return best[-1]
    epochs = sorted(glob.glob(os.path.join(work_dir, "epoch_*.pth")), key=os.path.getmtime)
    if epochs:
        return epochs[-1]
    raise RuntimeError("training produced no checkpoint")


def _strip_checkpoint(src: str, dst: str, meta: dict) -> None:
    """Keep only the (EMA) weights; drop optimizer/scheduler state."""
    ckpt = torch.load(src, map_location="cpu")
    torch.save({"state_dict": ckpt["state_dict"], "meta": meta}, dst)


def _compare_with_production(work_root: str, new_metrics: dict, coco_val: dict, samples: list[dict],
                             hard_negatives: list[dict], image_dir: str, width: int, height: int,
                             eval_conf: float, nms_iou: float) -> dict | None:
    """Evaluate the current production model on the same data for a fair comparison.

    A lower hard-negative FP rate only counts if recall does not suffer: the
    comparison reports per-class deltas and warnings.
    """
    import openvino as ov

    with session_factory()() as session:
        prod = session.query(ModelVersion).filter(ModelVersion.status == ModelStatus.production).first()
        if prod is None:
            return None
        version, xml_key, prod_classes = prod.version, prod.openvino_key, tuple(prod.class_names)
    try:
        s3 = storage()
        target = os.path.join(work_root, "baseline")
        s3.download_file(s3.settings.bucket_models, xml_key, os.path.join(target, "model.xml"))
        s3.download_file(s3.settings.bucket_models, xml_key[: -len(".xml")] + ".bin", os.path.join(target, "model.bin"))
        detector = OpenVinoDetector(ov.Core(), os.path.join(target, "model.xml"), width, height)
        baseline = evaluate_detector(detector, coco_val, samples, prod_classes, eval_conf, nms_iou,
                                     hard_negatives=hard_negatives, image_dir=image_dir)
        return compare(new_metrics, baseline, version)
    except Exception:  # the comparison is informative only
        log.exception("comparison with production model %s failed", version)
        return None


def run_training(run_id: int) -> None:
    settings = get_settings()
    s3 = storage()
    work_root = os.path.join(settings.work_dir, f"run-{run_id}")
    shutil.rmtree(work_root, ignore_errors=True)
    os.makedirs(work_root, exist_ok=True)

    with session_factory()() as session:
        run = session.get(TrainingRun, run_id)
        if run is None:
            raise RuntimeError(f"training run {run_id} does not exist")
        if run.status != TrainingStatus.queued:
            log.warning("run %s has status %s, skipping", run_id, run.status.value)
            return
        run.status = TrainingStatus.running
        run.started_at = utcnow()
        run.error = None
        session.commit()
        params = dict(
            base_model_id=run.base_model_id, width=run.input_width, height=run.input_height, epochs=run.epochs,
            batch_size=run.batch_size, learning_rate=run.learning_rate,
            num_workers=int((run.params_json or {}).get("num_workers", 4)),
        )
        class_names = list(run.class_names or [c.name for c in list_classes(session, active_only=True)])
        mapping = coco_index_mapping(c for c in list_classes(session) if c.name in class_names)
        params["class_names"] = class_names
        eval_conf = float(get_setting(session, "eval_confidence"))
        nms_iou = float(get_setting(session, "nms_iou_threshold"))

    reporter = RunReporter(run_id, os.path.join(work_root, "train.log"))
    handler = reporter.handler()
    root = logging.getLogger()
    root.addHandler(handler)
    runner = None
    try:
        log.info("training run %s started with %s", run_id, json.dumps(params))
        log.info("torch %s, CUDA available: %s%s", torch.__version__, torch.cuda.is_available(),
                 f" ({torch.cuda.get_device_name(0)})" if torch.cuda.is_available() else "")
        reporter.progress(phase="dataset", percent=0)

        # 1) dataset snapshot
        with session_factory()() as session:
            snapshot = create_snapshot(session, s3, run_id, work_root, class_names)
        _update_run(run_id, dataset_snapshot=snapshot.prefix, dataset_stats_json=snapshot.stats)

        # 2) initial weights
        reporter.progress(phase="preparing", percent=1)
        ckpt_dir = os.path.join(work_root, "checkpoints")
        os.makedirs(ckpt_dir, exist_ok=True)
        try:  # COCO base model of a given size ...
            base = get_base_model(params["base_model_id"])
            source_version = None
        except KeyError:  # ... or continue training an own model version (same size)
            with session_factory()() as session:
                source_version = session.query(ModelVersion).filter_by(version=params["base_model_id"]).one()
                base = base_model_for_architecture(source_version.architecture)
                base_key, source_classes = source_version.checkpoint_key, list(source_version.class_names)
        log.info("architecture: %s", base.architecture)
        coco_ckpt = ensure_base_checkpoint(base, os.path.join(settings.work_dir, "base"))
        if source_version is None:
            source_ckpt, source_classes = coco_ckpt, list(COCO_CLASSES)
        else:
            source_ckpt = os.path.join(ckpt_dir, "base.pth")
            s3.download_file(s3.settings.bucket_models, base_key, source_ckpt)
        init_ckpt, head_report = build_init_checkpoint(
            source_ckpt, source_classes, class_names, mapping, os.path.join(ckpt_dir, "init.pth"), coco_ckpt=coco_ckpt
        )
        log.info("initial weights from %s; classification head per class: %s", params["base_model_id"], json.dumps(head_report))

        # 3) training
        from mmengine.runner import Runner
        from mmdet.utils import register_all_modules

        register_all_modules(init_default_scope=True)
        use_amp = torch.cuda.is_available()
        tp = TrainParams(
            base=base,
            data_root=snapshot.local_dir,
            class_names=tuple(class_names),
            work_dir=os.path.join(work_root, "mmdet"),
            load_from=init_ckpt,
            input_width=params["width"],
            input_height=params["height"],
            epochs=params["epochs"],
            batch_size=params["batch_size"],
            learning_rate=params["learning_rate"],
            num_workers=params["num_workers"],
            num_train_images=snapshot.stats["train"]["images"],
            use_amp=use_amp,
            seed=run_id,
        )
        cfg = build_config(tp)
        lr = params["learning_rate"] or default_learning_rate(params["batch_size"])
        _update_run(run_id, learning_rate=lr)
        runner = Runner.from_cfg(cfg)
        runner.logger.addHandler(handler)
        hook = ProgressHookFactory.create(reporter, phase_offset=0.02, phase_weight=0.88)
        runner.register_hook(hook)
        runner.train()
        val_history = hook.val_history

        # 4) export best checkpoint
        reporter.progress(phase="export", percent=91)
        best_ckpt = _find_best_checkpoint(tp.work_dir)
        log.info("best checkpoint: %s", os.path.basename(best_ckpt))
        export_dir = os.path.join(work_root, "export")
        os.makedirs(export_dir, exist_ok=True)
        ckpt_path = os.path.join(export_dir, "checkpoint.pth")
        _strip_checkpoint(best_ckpt, ckpt_path, {"training_run_id": run_id, "classes": class_names,
                                                 "source_checkpoint": os.path.basename(best_ckpt)})
        config_path = os.path.join(export_dir, "config.py")
        cfg.dump(config_path)
        detector = build_detector(cfg, ckpt_path)
        wrapper = RTMDetDeployWrapper(detector)
        onnx_path = os.path.join(export_dir, "model.onnx")
        export_onnx(wrapper, onnx_path, params["width"], params["height"])
        ov_dir = os.path.join(export_dir, "openvino")
        xml_path = export_openvino(onnx_path, ov_dir)
        verification = verify_openvino(wrapper, xml_path, [(params["width"], params["height"])])

        # 5) evaluation of the exported model
        reporter.progress(phase="evaluation", percent=95)
        import openvino as ov

        coco_val, samples = load_val_samples(snapshot.local_dir)
        ov_detector = OpenVinoDetector(ov.Core(), xml_path, params["width"], params["height"])
        hard_negatives = load_hard_negatives(snapshot.local_dir)
        image_dir = os.path.join(snapshot.local_dir, "images")
        metrics = evaluate_detector(ov_detector, coco_val, samples, tuple(class_names), eval_conf, nms_iou,
                                    hard_negatives=hard_negatives, image_dir=image_dir)
        comparison = _compare_with_production(work_root, metrics, coco_val, samples, hard_negatives, image_dir,
                                              params["width"], params["height"], eval_conf, nms_iou)
        if comparison:
            metrics["comparison"] = comparison
            for w in comparison["warnings"]:
                log.warning("compared with %s: %s", comparison["baseline_model"], w)
        metrics["mmdet_val_history"] = val_history
        metrics["export_verification"] = verification
        metrics["head_init"] = head_report
        metrics_path = os.path.join(export_dir, "metrics.json")
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=1)
        o = metrics["overall"]
        log.info("evaluation: precision=%s recall=%s mAP50=%s mAP50-95=%s", o["precision"], o["recall"], o["mAP50"], o["mAP50-95"])
        if metrics.get("hard_negatives"):
            hn = metrics["hard_negatives"]["overall"]
            log.info("hard negatives: %s of %s still detected (FP rate %s)", hn["still_detected"], hn["total"], hn["fp_rate"])

        # 6) register candidate (never production automatically)
        reporter.progress(phase="publishing", percent=98)
        mv = publish_model(
            Artifacts(checkpoint_path=ckpt_path, onnx_path=onnx_path, openvino_dir=ov_dir,
                      config_path=config_path, metrics_path=metrics_path),
            kind="trained",
            architecture=base.architecture,
            input_width=params["width"],
            input_height=params["height"],
            class_names=class_names,
            metrics=metrics,
            training_run_id=run_id,
            dataset_snapshot=snapshot.prefix,
            notes=f"Training run #{run_id} from {params['base_model_id']}",
        )
        reporter.progress(phase="completed", percent=100)
        log.info("training run %s completed -> %s (candidate)", run_id, mv.version)
        _update_run(run_id, status=TrainingStatus.completed, finished_at=utcnow(), metrics_json=metrics, model_version_id=mv.id)
    except BaseException as exc:
        log.error("training run %s failed: %s\n%s", run_id, exc, traceback.format_exc())
        reporter.progress(phase="failed")
        _update_run(run_id, status=TrainingStatus.failed, finished_at=utcnow(), error=f"{exc.__class__.__name__}: {exc}"[:4000])
        raise
    finally:
        root.removeHandler(handler)
        if runner is not None:
            runner.logger.removeHandler(handler)
        reporter.close()
        try:
            log_key = f"training-runs/{run_id}/train.log"
            s3.upload_file(s3.settings.bucket_models, log_key, reporter.log_file, "text/plain")
            _update_run(run_id, log_key=log_key)
        except Exception:
            log.exception("could not upload training log")
        shutil.rmtree(work_root, ignore_errors=True)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
