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
from typing import Callable

import cv2
import numpy as np

from odcore.geometry import box_iou, xywh_to_xyxy

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
    if not coco_gt["annotations"]:
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
    """Greedy matching per image and class at a fixed confidence threshold."""
    gts: dict[tuple[int, int], list] = {}
    for a in coco_gt["annotations"]:
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
                else:
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


def evaluate_detector(detector, coco_gt: dict, samples: list[dict], class_names: tuple[str, ...],
                      eval_conf: float, iou_nms: float) -> dict:
    """Run an ``OpenVinoDetector`` on all samples and compute the metric set."""
    preds = predict_all(lambda img: detector.detect(img, 0.001, iou_nms).detections, samples)
    maps = coco_map(coco_gt, preds, class_names)
    prs = precision_recall(coco_gt, preds, class_names, eval_conf)

    def merge(m: dict, p: dict) -> dict:
        return {
            "precision": p.get("precision"), "recall": p.get("recall"),
            "mAP50": m.get("mAP50"), "mAP50-95": m.get("mAP50-95"),
            "tp": p.get("tp"), "fp": p.get("fp"), "fn": p.get("fn"),
        }

    per_class = {}
    for name in class_names:
        m = maps["per_class"].get(name, {})
        per_class[name] = merge(m, prs["per_class"][name])
        if "small" in m:
            per_class[name]["small"] = m["small"]
    return {
        "evaluated_with": "openvino",
        "input_size": f"{detector.input_width}x{detector.input_height}",
        "num_images": len(samples),
        "num_boxes": len(coco_gt["annotations"]),
        "confidence_for_pr": eval_conf,
        "overall": merge(maps["overall"], prs["overall"]),
        "per_class": per_class,
        "per_size": {s: merge(maps["per_size"].get(s, {}), prs["per_size"][s]) for s in AREA_RANGES},
    }
