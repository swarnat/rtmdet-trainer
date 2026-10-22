"""Evaluation of the *exported* OpenVINO model on the validation split.

The deployable artifact is evaluated with exactly the same preprocessing and
post-processing as the API, so the stored metrics describe what ``/detect``
actually returns.

Metrics:
* mAP50-95, mAP50 (COCO protocol via pycocotools), overall, per class and per
  box size (COCO areas: small < 32², medium < 96², large; in original pixels)
* precision / recall at a fixed confidence (default 0.25) and IoU 0.5 with
  greedy one-to-one matching, overall, per class and per box size
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
from dataclasses import replace
from typing import Callable

import cv2
import numpy as np

from odcore.geometry import IGNORE_COVERAGE, box_ioa, box_iou, xywh_to_xyxy

log = logging.getLogger(__name__)

AREA_RANGES = {"small": (0, 32**2), "medium": (32**2, 96**2), "large": (96**2, float("inf"))}
COCO_AREA_INDEX = {"all": 0, "small": 1, "medium": 2, "large": 3}


def _area_bucket(area: float) -> str:
    for name, (lo, hi) in AREA_RANGES.items():
        if lo <= area < hi:
            return name
    return "large"


def predict_all(detect: Callable[[np.ndarray], list], samples: list[dict]) -> dict[int, list]:
    preds = {}
    for i, s in enumerate(samples):
        image = cv2.imread(s["path"], cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"cannot read {s['path']}")
        preds[s["id"]] = detect(image)
        if (i + 1) % 50 == 0:
            log.info("evaluated %d/%d validation images", i + 1, len(samples))
    return preds


def num_boxes(coco: dict) -> int:
    """Number of real boxes (ignore regions are exported as ``iscrowd`` boxes and do not count)."""
    return sum(1 for a in coco["annotations"] if not a.get("iscrowd"))


def coco_map(coco_gt: dict, preds: dict[int, list], class_names: tuple[str, ...]) -> dict:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    results = [
        {
            "image_id": img_id,
            "category_id": d.class_id + 1,
            "bbox": [d.x1, d.y1, d.x2 - d.x1, d.y2 - d.y1],
            "score": d.confidence,
        }
        for img_id, dets in preds.items()
        for d in dets
    ]
    empty = {"mAP50-95": 0.0, "mAP50": 0.0}
    out: dict = {"overall": dict(empty), "per_class": {}, "per_size": {}}
    if num_boxes(coco_gt) == 0:
        log.warning("validation set has no boxes; mAP undefined")
        out["overall"] = {"mAP50-95": None, "mAP50": None}
        return out
    with contextlib.redirect_stdout(io.StringIO()):
        gt = COCO()
        gt.dataset = coco_gt
        gt.createIndex()
        if not results:
            for i, name in enumerate(class_names):
                out["per_class"][name] = dict(empty)
            return out
        dt = gt.loadRes(results)
        ev = COCOeval(gt, dt, "bbox")
        ev.evaluate()
        ev.accumulate()
    precision = ev.eval["precision"]  # [T, R, K, A, M]; M index 2 = maxDets 100

    def _mean(p: np.ndarray) -> float | None:
        p = p[p > -1]
        return float(p.mean()) if p.size else None

    def summarise(k: slice | int, a: int) -> dict:
        return {"mAP50-95": _mean(precision[:, :, k, a, 2]), "mAP50": _mean(precision[0, :, k, a, 2])}

    out["overall"] = summarise(slice(None), 0)
    for size, a in COCO_AREA_INDEX.items():
        if size != "all":
            out["per_size"][size] = summarise(slice(None), a)
    cat_ids = ev.params.catIds
    for k, cat_id in enumerate(cat_ids):
        name = class_names[cat_id - 1]
        out["per_class"][name] = summarise(k, 0)
        out["per_class"][name]["small"] = summarise(k, 1)
    return out


def precision_recall(coco_gt: dict, preds: dict[int, list], class_names: tuple[str, ...], conf: float, iou_thr: float = 0.5) -> dict:
    """Greedy matching per image and class at a fixed confidence threshold.

    Ignore regions (``iscrowd``, they apply to every class) are neither missed objects nor a reason
    for false positives: unmatched detections mostly inside one of them are skipped.
    """
    gts: dict[tuple[int, int], list] = {}
    ignore: dict[int, dict[tuple, list]] = {}
    for a in coco_gt["annotations"]:
        if a.get("iscrowd"):  # exported once per class: keep one per box
            ignore.setdefault(a["image_id"], {})[tuple(a["bbox"])] = a["bbox"]
        else:
            gts.setdefault((a["image_id"], a["category_id"] - 1), []).append(a)

    keys = list(class_names) + list(AREA_RANGES)
    tp = {k: 0 for k in keys}
    fp = {k: 0 for k in keys}
    fn = {k: 0 for k in keys}
    tot = {"tp": 0, "fp": 0, "fn": 0}

    image_ids = [im["id"] for im in coco_gt["images"]]
    for img_id in image_ids:
        dets = [d for d in preds.get(img_id, []) if d.confidence >= conf]
        for c, name in enumerate(class_names):
            cd = sorted((d for d in dets if d.class_id == c), key=lambda d: -d.confidence)
            cg = gts.get((img_id, c), [])
            g_boxes = np.array([xywh_to_xyxy(g["bbox"]) for g in cg]).reshape(-1, 4)
            g_used = np.zeros(len(cg), dtype=bool)
            d_boxes = np.array([[d.x1, d.y1, d.x2, d.y2] for d in cd]).reshape(-1, 4)
            ious = box_iou(d_boxes, g_boxes) if len(cd) and len(cg) else np.zeros((len(cd), len(cg)))
            regions = np.array([xywh_to_xyxy(b) for b in ignore.get(img_id, {}).values()]).reshape(-1, 4)
            covered = box_ioa(d_boxes, regions).max(axis=1) >= IGNORE_COVERAGE if len(cd) and len(regions) else np.zeros(len(cd), bool)
            for i, d in enumerate(cd):
                best, best_j = iou_thr, -1
                for j in range(len(cg)):
                    if not g_used[j] and ious[i, j] >= best:
                        best, best_j = ious[i, j], j
                d_area = (d.x2 - d.x1) * (d.y2 - d.y1)
                if best_j >= 0:
                    g_used[best_j] = True
                    tp[name] += 1
                    tp[_area_bucket(cg[best_j]["area"])] += 1
                    tot["tp"] += 1
                elif not covered[i]:
                    fp[name] += 1
                    fp[_area_bucket(d_area)] += 1
                    tot["fp"] += 1
            for j, used in enumerate(g_used):
                if not used:
                    fn[name] += 1
                    fn[_area_bucket(cg[j]["area"])] += 1
                    tot["fn"] += 1

    def pr(t: int, f_p: int, f_n: int) -> dict:
        return {
            "precision": t / (t + f_p) if t + f_p else None,
            "recall": t / (t + f_n) if t + f_n else None,
            "tp": t, "fp": f_p, "fn": f_n,
        }

    return {
        "confidence": conf,
        "iou": iou_thr,
        "overall": pr(tot["tp"], tot["fp"], tot["fn"]),
        "per_class": {n: pr(tp[n], fp[n], fn[n]) for n in class_names},
        "per_size": {s: pr(tp[s], fp[s], fn[s]) for s in AREA_RANGES},
    }


def remap_predictions(preds: dict[int, list], model_classes: tuple[str, ...], gt_classes: tuple[str, ...]) -> dict[int, list]:
    """Translate model class indices to ground-truth class indices by name; drop unknown classes."""
    index = {i: gt_classes.index(n) for i, n in enumerate(model_classes) if n in gt_classes}
    return {
        img_id: [replace(d, class_id=index[d.class_id]) for d in dets if d.class_id in index]
        for img_id, dets in preds.items()
    }


def hard_negative_regression(detect: Callable[[np.ndarray], list], hard_negatives: list[dict], image_dir: str,
                             model_classes: tuple[str, ...], conf: float, iou_thr: float = 0.5,
                             cache: dict[int, list] | None = None) -> dict:
    """Does the model still detect the stored false positives?

    A hard negative counts as "still detected" if a detection of the same
    class with confidence >= ``conf`` overlaps its box with IoU >= ``iou_thr``.
    Hard negatives of classes the model does not have are skipped.
    """
    cache = dict(cache or {})
    names = list(model_classes)
    buckets: dict[str, dict] = {}

    def bump(key: str, hit: bool) -> None:
        b = buckets.setdefault(key, {"total": 0, "still_detected": 0})
        b["total"] += 1
        b["still_detected"] += int(hit)

    for hn in hard_negatives:
        if hn["class"] not in names:
            continue
        if hn["image_id"] not in cache:
            image = cv2.imread(os.path.join(image_dir, hn["file_name"]), cv2.IMREAD_COLOR)
            if image is None:
                raise RuntimeError(f"cannot read {hn['file_name']}")
            cache[hn["image_id"]] = detect(image)
        cls = names.index(hn["class"])
        boxes = np.array([[d.x1, d.y1, d.x2, d.y2] for d in cache[hn["image_id"]] if d.class_id == cls and d.confidence >= conf])
        hit = bool(len(boxes)) and float(box_iou(np.array([hn["bbox"]]), boxes).max()) >= iou_thr
        keys = ["overall", f"class:{hn['class']}", f"split:{hn['split']}"]
        if hn["split"] == "validation":
            keys.append(f"val_class:{hn['class']}")
        for key in keys:
            bump(key, hit)

    def finish(b: dict | None) -> dict:
        b = b or {"total": 0, "still_detected": 0}
        return {**b, "fp_rate": b["still_detected"] / b["total"] if b["total"] else None}

    return {
        "confidence": conf,
        "iou": iou_thr,
        "overall": finish(buckets.get("overall")),
        "validation_only": finish(buckets.get("split:validation")),
        "train_only": finish(buckets.get("split:train")),
        "per_class": {n: finish(buckets.get(f"class:{n}")) for n in names if f"class:{n}" in buckets},
        # only images the model never saw as training crops: the fair basis for comparing two models
        "per_class_validation": {n: finish(buckets.get(f"val_class:{n}")) for n in names if f"val_class:{n}" in buckets},
    }


def evaluate_detector(detector, coco_gt: dict, samples: list[dict], model_classes: tuple[str, ...],
                      eval_conf: float, iou_nms: float, hard_negatives: list[dict] | None = None,
                      image_dir: str | None = None) -> dict:
    """Run an ``OpenVinoDetector`` on all samples and compute the metric set.

    Classes are matched by name, so models with a different class list (e.g.
    the production model in the comparison) can be evaluated on the same data;
    ground-truth classes the model lacks get ``None`` metrics.
    """
    detect = lambda img: detector.detect(img, 0.001, iou_nms).detections  # noqa: E731
    raw = predict_all(detect, samples)
    gt_classes = tuple(c["name"] for c in sorted(coco_gt["categories"], key=lambda c: c["id"]))
    preds = remap_predictions(raw, model_classes, gt_classes)
    maps = coco_map(coco_gt, preds, gt_classes)
    prs = precision_recall(coco_gt, preds, gt_classes, eval_conf)

    def merge(m: dict, p: dict) -> dict:
        return {
            "precision": p.get("precision"), "recall": p.get("recall"),
            "mAP50": m.get("mAP50"), "mAP50-95": m.get("mAP50-95"),
            "tp": p.get("tp"), "fp": p.get("fp"), "fn": p.get("fn"),
        }

    per_class = {}
    for name in gt_classes:
        if name not in model_classes:
            per_class[name] = None  # model cannot detect this class
            continue
        m = maps["per_class"].get(name, {})
        per_class[name] = merge(m, prs["per_class"][name])
        if "small" in m:
            per_class[name]["small"] = m["small"]
    result = {
        "evaluated_with": "openvino",
        "input_size": f"{detector.input_width}x{detector.input_height}",
        "num_images": len(samples),
        "num_boxes": num_boxes(coco_gt),
        "confidence_for_pr": eval_conf,
        "overall": merge(maps["overall"], prs["overall"]),
        "per_class": per_class,
        "per_size": {s: merge(maps["per_size"].get(s, {}), prs["per_size"][s]) for s in AREA_RANGES},
    }
    if hard_negatives and image_dir:
        result["hard_negatives"] = hard_negative_regression(
            detect, hard_negatives, image_dir, model_classes, eval_conf, cache=raw
        )
    return result


# below this many validation boxes per class, one box shifts recall by more than 3 pp: deltas are not judged
MIN_RELIABLE_BOXES = 30


def compare(new: dict, baseline: dict, baseline_version: str, recall_tolerance: float = 0.02) -> dict:
    """Per-class deltas new - baseline, plus warnings when fewer false alarms come with lower recall.

    The hard-negative FP rate is compared on validation images only: the new model was trained on crops of
    all training-image hard negatives, the baseline usually on fewer, so including them favours the new model.
    """
    def delta(a, b):
        return None if a is None or b is None else a - b

    def hn_rate(metrics: dict, name: str):
        b = ((metrics.get("hard_negatives") or {}).get("per_class_validation") or {}).get(name)
        return b["fp_rate"] if b else None

    per_class = {}
    warnings = []
    for name, m in new["per_class"].items():
        b = baseline["per_class"].get(name)
        if m is None or b is None:
            continue
        entry = {k: delta(m.get(k), b.get(k)) for k in ("precision", "recall", "mAP50", "mAP50-95")}
        entry["hard_negative_fp_rate"] = delta(hn_rate(new, name), hn_rate(baseline, name))
        per_class[name] = entry
        if entry["recall"] is not None and entry["recall"] < -recall_tolerance:
            boxes = (m.get("tp") or 0) + (m.get("fn") or 0)
            note = f" (only {boxes} validation boxes)" if boxes < MIN_RELIABLE_BOXES else ""
            if entry["hard_negative_fp_rate"] is not None and entry["hard_negative_fp_rate"] < 0:
                warnings.append(f"{name}: fewer known false positives, but recall dropped by {-entry['recall']:.1%}{note}")
            else:
                warnings.append(f"{name}: recall dropped by {-entry['recall']:.1%}{note}")
    return {
        "baseline_model": baseline_version,
        "baseline": {"overall": baseline["overall"], "per_class": baseline["per_class"],
                     "hard_negatives": baseline.get("hard_negatives")},
        "delta_per_class": per_class,
        "hard_negative_basis": "validation",
        "min_reliable_boxes": MIN_RELIABLE_BOXES,
        "warnings": warnings,
    }
