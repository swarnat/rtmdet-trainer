"""Reproducible dataset snapshots in COCO detection format.

For every training run the labeled images are frozen into
``s3://<datasets>/<run-id>/``::

    manifest.json             image ids, sha256, splits, source keys, stats
    annotations/train.json    COCO detection format
    annotations/val.json
    images/<sha256>.<ext>     copies of the images (survive later deletions)

Splits are persisted on the image the first time it is used and never
re-rolled. Labeled images without boxes are included as negatives.
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from odcore.classes import CLASS_NAMES, CLASS_TO_ID
from odcore.db import AnnotationStatus, DatasetSplit, Image
from odcore.geometry import xyxy_to_xywh
from odcore.settings_store import get_setting
from odcore.splits import assign_split
from odcore.storage import ObjectStorage

log = logging.getLogger(__name__)

SPLIT_FILES = {DatasetSplit.train: "train.json", DatasetSplit.validation: "val.json"}


@dataclass
class Snapshot:
    prefix: str               # e.g. "17/" inside the datasets bucket
    local_dir: str
    stats: dict
    manifest: dict = field(repr=False)


def coco_categories() -> list[dict]:
    return [{"id": CLASS_TO_ID[name] + 1, "name": name, "supercategory": "object"} for name in CLASS_NAMES]


def image_file_name(image: Image) -> str:
    ext = posixpath.splitext(image.s3_object_key)[1] or ".jpg"
    return f"{image.sha256}{ext}"


def build_coco(images: list[Image]) -> dict:
    """Build a COCO detection dict. Category ids are 1-based (person=1, bicycle=2, vehicle=3)."""
    coco_images, coco_anns = [], []
    ann_id = 1
    for img in images:
        coco_images.append({"id": img.id, "file_name": image_file_name(img), "width": img.width, "height": img.height})
        for a in img.annotations:
            if a.class_name not in CLASS_TO_ID:
                log.warning("skipping annotation %s with unknown class %s", a.id, a.class_name)
                continue
            x, y, w, h = xyxy_to_xywh((a.x1, a.y1, a.x2, a.y2))
            if w < 1 or h < 1:
                continue
            coco_anns.append({
                "id": ann_id,
                "image_id": img.id,
                "category_id": CLASS_TO_ID[a.class_name] + 1,
                "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                "area": round(w * h, 2),
                "iscrowd": 0,
            })
            ann_id += 1
    return {
        "info": {"description": "object-detection dataset snapshot", "date_created": datetime.now(timezone.utc).isoformat()},
        "images": coco_images,
        "annotations": coco_anns,
        "categories": coco_categories(),
    }


def split_stats(coco: dict) -> dict:
    per_class = {name: 0 for name in CLASS_NAMES}
    with_boxes = set()
    for a in coco["annotations"]:
        per_class[CLASS_NAMES[a["category_id"] - 1]] += 1
        with_boxes.add(a["image_id"])
    return {
        "images": len(coco["images"]),
        "negative_images": len(coco["images"]) - len(with_boxes),
        "boxes": len(coco["annotations"]),
        "boxes_per_class": per_class,
    }


def create_snapshot(session: Session, s3: ObjectStorage, run_id: int, local_root: str) -> Snapshot:
    images = list(
        session.execute(
            select(Image)
            .where(Image.annotation_status == AnnotationStatus.labeled)
            .options(selectinload(Image.annotations))
            .order_by(Image.id)
        ).scalars()
    )
    ratio = float(get_setting(session, "validation_ratio"))
    for img in images:
        if img.dataset_split is None:
            img.dataset_split = DatasetSplit(assign_split(img.sha256, ratio))
    session.commit()

    by_split = {s: [i for i in images if i.dataset_split == s] for s in SPLIT_FILES}
    if not by_split[DatasetSplit.train]:
        raise RuntimeError("dataset has no labeled training images")
    if not by_split[DatasetSplit.validation]:
        raise RuntimeError("dataset has no labeled validation images")

    prefix = f"{run_id}/"
    bucket_ds = s3.settings.bucket_datasets
    bucket_img = s3.settings.bucket_images
    local_dir = os.path.join(local_root, "dataset")
    os.makedirs(os.path.join(local_dir, "annotations"), exist_ok=True)
    os.makedirs(os.path.join(local_dir, "images"), exist_ok=True)

    stats: dict = {}
    for split, file_name in SPLIT_FILES.items():
        coco = build_coco(by_split[split])
        stats[split.value] = split_stats(coco)
        path = os.path.join(local_dir, "annotations", file_name)
        with open(path, "w") as f:
            json.dump(coco, f)
        s3.upload_file(bucket_ds, f"{prefix}annotations/{file_name}", path, "application/json")

    def copy_one(img: Image) -> None:
        name = image_file_name(img)
        s3.copy(bucket_img, img.s3_object_key, bucket_ds, f"{prefix}images/{name}")
        s3.download_file(bucket_ds, f"{prefix}images/{name}", os.path.join(local_dir, "images", name))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(copy_one, images))

    manifest = {
        "training_run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classes": list(CLASS_NAMES),
        "validation_ratio_for_new_images": ratio,
        "format": "coco-detection",
        "stats": stats,
        "images": [
            {
                "id": i.id,
                "sha256": i.sha256,
                "split": i.dataset_split.value,
                "file_name": image_file_name(i),
                "source_key": i.s3_object_key,
                "width": i.width,
                "height": i.height,
                "boxes": len(i.annotations),
            }
            for i in images
        ],
    }
    path = os.path.join(local_dir, "manifest.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=1)
    s3.upload_file(bucket_ds, f"{prefix}manifest.json", path, "application/json")
    log.info("dataset snapshot s3://%s/%s: %s", bucket_ds, prefix, json.dumps(stats))
    return Snapshot(prefix=f"{bucket_ds}/{prefix}", local_dir=local_dir, stats=stats, manifest=manifest)


def load_val_samples(local_dir: str) -> tuple[dict, list[dict]]:
    """Return the COCO val dict and per-image samples with absolute image paths."""
    with open(os.path.join(local_dir, "annotations", "val.json")) as f:
        coco = json.load(f)
    samples = [
        {"id": im["id"], "path": os.path.join(local_dir, "images", im["file_name"]), "width": im["width"], "height": im["height"]}
        for im in coco["images"]
    ]
    return coco, samples


def current_validation_set(session: Session, s3: ObjectStorage, local_root: str) -> str | None:
    """Download the current labeled validation images (used to evaluate the COCO bootstrap model)."""
    images = list(
        session.execute(
            select(Image)
            .where(Image.annotation_status == AnnotationStatus.labeled, Image.dataset_split == DatasetSplit.validation)
            .options(selectinload(Image.annotations))
        ).scalars()
    )
    if not images:
        return None
    local_dir = os.path.join(local_root, "val-current")
    os.makedirs(os.path.join(local_dir, "annotations"), exist_ok=True)
    with open(os.path.join(local_dir, "annotations", "val.json"), "w") as f:
        json.dump(build_coco(images), f)
    for img in images:
        s3.download_file(s3.settings.bucket_images, img.s3_object_key, os.path.join(local_dir, "images", image_file_name(img)))
    return local_dir
