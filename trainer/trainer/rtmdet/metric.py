"""COCO metric with mAP per class and per box size for the per-epoch validation chart.

MMDetection's ``CocoMetric`` only reports mAP50-95 per class (``classwise``) and
overall values per box size. This subclass additionally evaluates the same
predictions with ``evaluate.coco_map`` (as used for the exported model) and
returns ``detail/class/<name>/<metric>`` and ``detail/size/<size>/<metric>``.
"""
from __future__ import annotations

import logging

from mmdet.evaluation.metrics import CocoMetric
from mmdet.registry import METRICS

from odcore.geometry import Detection

from ..evaluate import coco_map

log = logging.getLogger(__name__)


def detailed_maps(coco_gt: dict, cat_ids: list[int], preds: list[dict]) -> dict[str, float]:
    """``preds``: MMDetection results (``img_id``, ``bboxes`` xyxy, ``scores``, ``labels`` = index into ``cat_ids``)."""
    class_names = tuple(c["name"] for c in sorted(coco_gt["categories"], key=lambda c: c["id"]))
    dets: dict[int, list] = {}
    for p in preds:
        dets[p["img_id"]] = [
            Detection(cat_ids[int(label)] - 1, float(score), *map(float, box))
            for box, score, label in zip(p["bboxes"], p["scores"], p["labels"])
        ]
    maps = coco_map(coco_gt, dets, class_names)
    out = {}
    for group, values in (("class", maps["per_class"]), ("size", maps["per_size"])):
        for name, m in values.items():
            for metric, v in m.items():
                if isinstance(v, float):  # None = no ground truth for this class/size
                    out[f"detail/{group}/{name}/{metric}"] = v
    return out


@METRICS.register_module()
class DetailedCocoMetric(CocoMetric):
    def compute_metrics(self, results: list) -> dict[str, float]:
        metrics = super().compute_metrics(results)
        try:
            metrics.update(detailed_maps(self._coco_api.dataset, list(self.cat_ids), [pred for _, pred in results]))
        except Exception:  # the chart details must never break the training
            log.exception("per-class/per-size validation metrics failed")
        return metrics
