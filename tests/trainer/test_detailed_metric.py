"""Per-class / per-size mAP for the per-epoch validation chart."""
from __future__ import annotations

import numpy as np
import pytest

from trainer.rtmdet.metric import detailed_maps


def test_detailed_maps_per_class_and_size():
    coco_gt = {
        "images": [{"id": 1, "width": 1920, "height": 1080, "file_name": "a.jpg"}],
        "categories": [{"id": 1, "name": "person"}, {"id": 2, "name": "vehicle"}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [100, 100, 200, 400], "area": 80000, "iscrowd": 0},
            {"id": 2, "image_id": 1, "category_id": 2, "bbox": [800, 500, 20, 20], "area": 400, "iscrowd": 0},
        ],
    }
    # person found exactly, vehicle missed; MMDetection labels index into cat_ids
    preds = [{"img_id": 1, "bboxes": np.array([[100, 100, 300, 500]], dtype=np.float32),
              "scores": np.array([0.9], dtype=np.float32), "labels": np.array([0])}]
    out = detailed_maps(coco_gt, [1, 2], preds)
    assert out["detail/class/person/mAP50"] == pytest.approx(1.0)
    assert out["detail/class/vehicle/mAP50"] == pytest.approx(0.0)
    assert out["detail/size/large/mAP50-95"] == pytest.approx(1.0)
    assert out["detail/size/small/mAP50"] == pytest.approx(0.0)
    assert not any("medium" in k for k in out)  # no ground truth of this size -> no value
