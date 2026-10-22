"""Hard-negative crops, oversampling, regression check and model comparison."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from odcore.db import Annotation, Base, DatasetSplit, Image
from odcore.geometry import Detection
from trainer.dataset import add_hard_negative_crops, build_coco
from trainer.evaluate import compare, hard_negative_regression, remap_predictions
from trainer.hard_negatives import Rect, compute_crop, transform_boxes


@pytest.mark.parametrize("box", [(900, 500, 940, 570), (0, 0, 30, 60), (1880, 1040, 1920, 1080), (200, 100, 1700, 1000)])
def test_crop_contains_box_and_stays_in_image(box):
    crop = compute_crop(1920, 1080, box, context_factor=3.0, min_crop_fraction=0.25)
    assert 0 <= crop.x1 <= box[0] and box[2] <= crop.x2 <= 1920
    assert 0 <= crop.y1 <= box[1] and box[3] <= crop.y2 <= 1080


def test_crop_size_aspect_and_minimum():
    # small box: minimum width (25 % of 1920 = 480) with 16:9 aspect wins over 3x context
    crop = compute_crop(1920, 1080, (900, 500, 940, 570), 3.0, 0.25)
    assert (crop.width, crop.height) == (480, 270)
    # larger box: 3x the box height, widened to 16:9
    crop = compute_crop(1920, 1080, (800, 400, 900, 600), 3.0, 0.25)
    assert crop.height == 600 and crop.width == round(600 * 16 / 9)
    assert crop.x1 <= 850 - crop.width / 2 + 1  # centred on the box


def test_transform_boxes_clips_and_shifts():
    crop = Rect(100, 100, 580, 370)
    out = transform_boxes([("person", 120, 150, 200, 300), ("vehicle", 500, 300, 700, 500), ("person", 0, 0, 50, 50)], crop)
    assert out == [("person", 20, 50, 100, 200), ("vehicle", 400, 200, 480, 270)]


def image(session, id_, split, anns, tmp_path):
    img = Image(id=id_, s3_object_key=f"images/{id_:064d}.jpg", sha256=f"{id_:064d}", content_type="image/jpeg", size_bytes=1,
                width=1920, height=1080, dataset_split=split)
    img.annotations = [Annotation(id=id_ * 10 + i, class_name=c, type=t, x1=x1, y1=y1, x2=x2, y2=y2)
                       for i, (c, t, x1, y1, x2, y2) in enumerate(anns)]
    session.add(img)
    session.commit()
    os.makedirs(tmp_path / "images", exist_ok=True)
    cv2.imwrite(str(tmp_path / "images" / f"{id_:064d}.jpg"), np.full((1080, 1920, 3), 90, np.uint8))
    return img


def test_hard_negative_crops_are_oversampled_without_positive_for_false_class(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    train = image(session, 1, DatasetSplit.train, [
        ("person", "hard_negative", 900, 500, 940, 570),   # a sign detected as person
        ("vehicle", "positive", 1000, 520, 1100, 600),     # real car next to it
        ("person", "positive", 100, 100, 150, 250),        # far away, outside the crop
    ], tmp_path)
    val = image(session, 2, DatasetSplit.validation, [("person", "hard_negative", 10, 10, 50, 90)], tmp_path)
    classes = ["person", "vehicle"]
    coco = build_coco([train], classes)
    assert len(coco["images"]) == 1 and len(coco["annotations"]) == 2  # hard negative is not a box

    records, stats = add_hard_negative_crops(session, coco, [train, val], classes, str(tmp_path))
    assert stats["total"] == 2 and stats["train_crops"] == 1 and stats["per_class"] == {"person": 2, "vehicle": 0}
    crop_images = [im for im in coco["images"] if im["file_name"] == "hn_10.jpg"]
    assert len(crop_images) == 3  # default oversampling
    assert len({im["id"] for im in coco["images"]}) == len(coco["images"])
    for im in crop_images:
        anns = [a for a in coco["annotations"] if a["image_id"] == im["id"]]
        assert [a["category_id"] for a in anns] == [2]  # only the real vehicle, transformed into the crop
        x, y, w, h = anns[0]["bbox"]
        assert 0 <= x and x + w <= im["width"] and 0 <= y and y + h <= im["height"]
    assert cv2.imread(str(tmp_path / "images" / "hn_10.jpg")).shape[:2] == (crop_images[0]["height"], crop_images[0]["width"])
    assert [r["split"] for r in records] == ["train", "validation"]
    assert "crop_file" not in records[1]  # validation hard negatives: regression only, no training crop


def test_hard_negative_regression_counts_same_class_overlaps():
    hns = [
        {"image_id": 1, "file_name": "a.jpg", "class": "person", "bbox": [100, 100, 140, 170], "split": "train"},
        {"image_id": 1, "file_name": "a.jpg", "class": "person", "bbox": [500, 100, 540, 170], "split": "validation"},
        {"image_id": 2, "file_name": "b.jpg", "class": "vehicle", "bbox": [0, 0, 100, 100], "split": "train"},
        {"image_id": 2, "file_name": "b.jpg", "class": "battery", "bbox": [0, 0, 10, 10], "split": "train"},  # unknown to model
    ]
    cache = {
        1: [Detection(0, 0.6, 101, 102, 141, 171), Detection(1, 0.9, 500, 100, 540, 170)],  # second: other class
        2: [Detection(1, 0.1, 0, 0, 100, 100)],  # below confidence
    }
    res = hard_negative_regression(lambda img: [], hns, "/nonexistent", ("person", "vehicle"), conf=0.25, cache=cache)
    assert res["overall"] == {"total": 3, "still_detected": 1, "fp_rate": 1 / 3}
    assert res["per_class"]["person"]["fp_rate"] == 0.5
    assert res["validation_only"] == {"total": 1, "still_detected": 0, "fp_rate": 0.0}
    # per-class buckets restricted to validation images (fair basis for the model comparison)
    assert res["per_class_validation"] == {"person": {"total": 1, "still_detected": 0, "fp_rate": 0.0}}


def test_remap_by_class_name():
    preds = {1: [Detection(0, 0.9, 0, 0, 1, 1), Detection(1, 0.8, 0, 0, 1, 1)]}
    out = remap_predictions(preds, ("vehicle", "chair"), ("person", "vehicle"))
    assert [(d.class_id, d.confidence) for d in out[1]] == [(1, 0.9)]


def _metrics(recall, rate, train_rate=None, boxes=100):
    tp = round(recall * boxes)
    return {"overall": {},
            "per_class": {"person": {"precision": 0.8, "recall": recall, "mAP50": 0.7, "mAP50-95": 0.4, "tp": tp, "fp": 0, "fn": boxes - tp}},
            "hard_negatives": {
                "per_class": {"person": {"total": 20, "still_detected": 0, "fp_rate": train_rate if train_rate is not None else rate}},
                "per_class_validation": {"person": {"total": 10, "still_detected": int(rate * 10), "fp_rate": rate}},
            }}


def test_compare_warns_when_fewer_false_alarms_cost_recall():
    cmp = compare(_metrics(0.70, 0.1), _metrics(0.80, 0.5), "model-0001")
    d = cmp["delta_per_class"]["person"]
    assert d["recall"] == pytest.approx(-0.10) and d["hard_negative_fp_rate"] == pytest.approx(-0.4)
    assert cmp["warnings"] and "fewer known false positives" in cmp["warnings"][0]
    assert "only" not in cmp["warnings"][0]
    assert compare(_metrics(0.80, 0.1), _metrics(0.80, 0.5), "model-0001")["warnings"] == []


def test_compare_uses_validation_hard_negatives_only():
    # the new model "knows" its training hard negatives (rate 0 vs 0.8), on validation images both are equal
    cmp = compare(_metrics(0.8, 0.3, train_rate=0.0), _metrics(0.8, 0.3, train_rate=0.8), "model-0001")
    assert cmp["delta_per_class"]["person"]["hard_negative_fp_rate"] == pytest.approx(0.0)
    assert cmp["hard_negative_basis"] == "validation"


def test_compare_marks_warnings_on_few_boxes():
    cmp = compare(_metrics(4 / 6, 0.1, boxes=6), _metrics(5 / 6, 0.1, boxes=6), "model-0001")
    assert cmp["warnings"] == ["person: recall dropped by 16.7% (only 6 validation boxes)"]


def test_hard_negative_crops_keep_ignore_regions_as_crowd_boxes(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    train = image(session, 1, DatasetSplit.train, [
        ("person", "hard_negative", 900, 500, 940, 570),
        ("person", "ignore", 1000, 520, 1100, 600),      # unclear object next to it: inside the crop
        ("person", "ignore", 100, 100, 150, 250),        # far away: not in the crop
    ], tmp_path)
    classes = ["person", "vehicle"]
    coco = build_coco([train], classes)
    assert [a["iscrowd"] for a in coco["annotations"]] == [1, 1]
    add_hard_negative_crops(session, coco, [train], classes, str(tmp_path))
    for im in (im for im in coco["images"] if im["file_name"] == "hn_10.jpg"):
        anns = [a for a in coco["annotations"] if a["image_id"] == im["id"]]
        assert [a["iscrowd"] for a in anns] == [1]
