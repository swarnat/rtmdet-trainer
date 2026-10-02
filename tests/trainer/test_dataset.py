"""COCO snapshot building (incl. negative images) and evaluation metrics."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest

from odcore.db import Annotation, Image
from odcore.geometry import Detection
from trainer.dataset import build_coco, split_stats
from trainer.evaluate import precision_recall


def image(id_: int, boxes: list[tuple[str, float, float, float, float]]) -> Image:
    img = Image(id=id_, s3_object_key=f"images/{id_:064d}.jpg", sha256=f"{id_:064d}", content_type="image/jpeg",
                size_bytes=1, width=1920, height=1080)
    img.annotations = [Annotation(class_name=c, x1=x1, y1=y1, x2=x2, y2=y2) for c, x1, y1, x2, y2 in boxes]
    return img


def test_build_coco_includes_negative_images():
    coco = build_coco([
        image(1, [("person", 10, 20, 110, 220), ("vehicle", 500, 500, 900, 800)]),
        image(2, []),  # labeled image without objects = negative example
    ])
    assert [i["id"] for i in coco["images"]] == [1, 2]
    assert coco["images"][1]["file_name"].endswith(".jpg")
    assert [c["name"] for c in coco["categories"]] == ["person", "bicycle", "vehicle"]
    assert [c["id"] for c in coco["categories"]] == [1, 2, 3]
    a = coco["annotations"]
    assert len(a) == 2
    assert a[0]["bbox"] == [10, 20, 100, 200] and a[0]["category_id"] == 1 and a[0]["area"] == 20000
    assert a[1]["category_id"] == 3
    stats = split_stats(coco)
    assert stats["images"] == 2 and stats["negative_images"] == 1
    assert stats["boxes_per_class"] == {"person": 1, "bicycle": 0, "vehicle": 1}


def test_precision_recall_greedy_matching():
    coco = build_coco([image(1, [("person", 0, 0, 100, 100), ("person", 200, 0, 300, 100)]), image(2, [])])
    preds = {
        1: [
            Detection(0, 0.9, 2, 2, 100, 100),     # TP
            Detection(0, 0.8, 0, 0, 98, 98),       # duplicate -> FP
            Detection(2, 0.7, 200, 0, 300, 100),   # wrong class -> FP (vehicle)
            Detection(0, 0.1, 200, 0, 300, 100),   # below confidence -> ignored
        ],
        2: [Detection(1, 0.5, 10, 10, 20, 20)],     # FP on negative image (small bicycle)
    }
    res = precision_recall(coco, preds, ("person", "bicycle", "vehicle"), conf=0.25)
    assert res["overall"] == {"precision": 1 / 4, "recall": 1 / 2, "tp": 1, "fp": 3, "fn": 1}
    assert res["per_class"]["person"]["precision"] == pytest.approx(0.5)
    assert res["per_class"]["bicycle"]["recall"] is None
    assert res["per_size"]["small"]["fp"] == 1


def test_mmdet_config_keeps_negative_samples():
    pytest.importorskip("mmdet")
    from trainer.rtmdet.dataset_config import TrainParams, build_config

    cfg = build_config(TrainParams(data_root="/data", work_dir="/work", load_from="/init.pth", input_width=1536,
                                   input_height=864, epochs=30, batch_size=4, learning_rate=None, num_workers=2,
                                   num_train_images=100, use_amp=False, seed=1))
    ds = cfg.train_dataloader.dataset
    assert ds.filter_cfg.filter_empty_gt is False
    assert ds.metainfo["classes"] == ("person", "bicycle", "vehicle")
    assert cfg.model.bbox_head.num_classes == 3
    for step in ds.pipeline:
        if step["type"] == "RandomCrop":
            assert step["allow_negative_crop"] is True
            assert step["crop_size"] == (1536, 864)
        if step["type"] == "FilterAnnotations":
            assert step["keep_empty"] is False
    test_resize = [s for s in cfg.val_dataloader.dataset.pipeline if s["type"] == "Resize"][0]
    assert test_resize["scale"] == (1536, 864)
    assert cfg.train_cfg.max_epochs == 30
    switch = [h for h in cfg.custom_hooks if h["type"] == "PipelineSwitchHook"][0]
    assert switch["switch_epoch"] == 30 - 4
