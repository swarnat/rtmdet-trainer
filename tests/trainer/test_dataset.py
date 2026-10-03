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
    ], ["person", "bicycle", "vehicle"])
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


def test_build_coco_uses_run_class_order_and_drops_other_classes():
    coco = build_coco([image(1, [("person", 0, 0, 50, 50), ("battery", 100, 100, 150, 130)])], ["battery", "ladder"])
    assert [(c["id"], c["name"]) for c in coco["categories"]] == [(1, "battery"), (2, "ladder")]
    assert [(a["category_id"], a["bbox"]) for a in coco["annotations"]] == [(1, [100, 100, 50, 30])]
    assert split_stats(coco)["boxes_per_class"] == {"battery": 1, "ladder": 0}


def test_precision_recall_greedy_matching():
    coco = build_coco([image(1, [("person", 0, 0, 100, 100), ("person", 200, 0, 300, 100)]), image(2, [])],
                      ["person", "bicycle", "vehicle"])
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

    from odcore.architectures import get_base_model

    cfg = build_config(TrainParams(base=get_base_model("rtmdet-s-coco"), data_root="/data", class_names=("person", "bicycle", "vehicle"), work_dir="/work", load_from="/init.pth", input_width=1536,
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


def test_head_init_by_class_name(tmp_path):
    torch = pytest.importorskip("torch")
    from odcore.classes import COCO_CLASSES
    from trainer.rtmdet.base_config import build_init_checkpoint

    c_in = 4
    coco_w = torch.arange(80, dtype=torch.float32).view(80, 1, 1, 1).repeat(1, c_in, 1, 1)
    coco = {"bbox_head.rtm_cls.0.weight": coco_w, "bbox_head.rtm_cls.0.bias": torch.arange(80, dtype=torch.float32),
            "backbone.x": torch.ones(2)}
    torch.save({"state_dict": coco}, tmp_path / "coco.pth")
    mapping = {"person": [0], "vehicle": [2, 3, 5, 7]}  # car, motorcycle, bus, truck

    # from COCO: mapped classes get COCO rows (mean), unmapped class is freshly initialised
    path, report = build_init_checkpoint(str(tmp_path / "coco.pth"), COCO_CLASSES, ["person", "vehicle", "battery"],
                                         mapping, str(tmp_path / "init.pth"))
    st = torch.load(path)["state_dict"]
    assert st["bbox_head.rtm_cls.0.weight"].shape == (3, c_in, 1, 1)
    assert st["bbox_head.rtm_cls.0.bias"][:2].tolist() == [0.0, (2 + 3 + 5 + 7) / 4]
    assert st["bbox_head.rtm_cls.0.bias"][2].item() == pytest.approx(-4.595, abs=1e-3)
    assert torch.equal(st["backbone.x"], torch.ones(2))
    assert report == {"person": "COCO person", "vehicle": "COCO car+motorcycle+bus+truck", "battery": "random (new class)"}

    # continue from a trained model: existing classes by name, new class from COCO mapping
    trained = {"bbox_head.rtm_cls.0.weight": torch.full((2, c_in, 1, 1), 7.0), "bbox_head.rtm_cls.0.bias": torch.tensor([1.0, 2.0])}
    torch.save({"state_dict": trained}, tmp_path / "trained.pth")
    path, report = build_init_checkpoint(str(tmp_path / "trained.pth"), ["battery", "person"], ["person", "vehicle"],
                                         mapping, str(tmp_path / "init2.pth"), coco_ckpt=str(tmp_path / "coco.pth"))
    bias = torch.load(path)["state_dict"]["bbox_head.rtm_cls.0.bias"].tolist()
    assert bias == [2.0, (2 + 3 + 5 + 7) / 4]
    assert report == {"person": "source model", "vehicle": "COCO car+motorcycle+bus+truck"}


@pytest.mark.parametrize("base_id,widen,deepen", [("rtmdet-tiny-coco", 0.375, 0.167), ("rtmdet-s-coco", 0.5, 0.33), ("rtmdet-m-coco", 0.75, 0.67)])
def test_base_model_sizes(base_id, widen, deepen):
    pytest.importorskip("mmdet")
    from odcore.architectures import get_base_model
    from trainer.rtmdet.base_config import load_base_config

    base = get_base_model(base_id)
    cfg = load_base_config(base, num_classes=4)
    assert cfg.model.backbone.widen_factor == widen and cfg.model.backbone.deepen_factor == deepen
    assert cfg.model.bbox_head.num_classes == 4
    assert cfg.model.backbone.init_cfg is None
    assert cfg.model.backbone.norm_cfg["type"] == "BN" and cfg.model.bbox_head.norm_cfg["type"] == "BN"
    assert base.checkpoint_key.startswith("base/rtmdet_") and base.checkpoint_url.endswith(f"{base.sha256_prefix}.pth")
