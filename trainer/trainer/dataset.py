"""Reproducible dataset snapshots in COCO detection format.

For every training run the labeled images are frozen into
``s3://<datasets>/<run-id>/``::

    manifest.json             image ids, sha256, splits, source keys, stats
    annotations/train.json    COCO detection format
    annotations/val.json
    images/hn_<id>.jpg        hard-negative crops (derived per run)

The images themselves are not copied: the run links them (``odcore.snapshots``, link count
``images.snapshot_refs``) and they are read from the images bucket. Images are content-addressed
and immutable, and a linked image is only hidden when deleted, so the snapshot stays complete.

Splits are persisted on the image the first time it is used and never
re-rolled. Labeled images without boxes are included as negatives.

Only images that were checked for *every* class of the run are used
(``Image.reviewed_classes``); boxes of other classes are dropped, i.e. such
objects are background for this model.

Hard negatives (see ``hard_negatives.py``) of training images add background
crops ``images/hn_<annotation-id>.jpg`` to ``train.json`` (oversampled by
repeating the image entry). All hard negatives of the snapshot are listed in
``annotations/hard_negatives.json`` for the regression check.
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

from odcore.classes import is_reviewed_for
from odcore.db import AnnotationStatus, DatasetSplit, Image
from odcore.geometry import xyxy_to_xywh
from odcore.settings_store import get_setting
from odcore.snapshots import link_images
from odcore.splits import assign_split
from odcore.storage import ObjectStorage

from .hard_negatives import compute_crop, transform_boxes, write_crop

log = logging.getLogger(__name__)

SPLIT_FILES = {DatasetSplit.train: "train.json", DatasetSplit.validation: "val.json"}


@dataclass
class Snapshot:
    prefix: str               # e.g. "17/" inside the datasets bucket
    local_dir: str
    stats: dict
    manifest: dict = field(repr=False)


def coco_categories(class_names: list[str]) -> list[dict]:
    return [{"id": i + 1, "name": name, "supercategory": "object"} for i, name in enumerate(class_names)]


def image_file_name(image: Image) -> str:
    ext = posixpath.splitext(image.s3_object_key)[1] or ".jpg"
    return f"{image.sha256}{ext}"


def build_coco(images: list[Image], class_names: list[str]) -> dict:
    """Build a COCO detection dict. Category ids are 1-based in the order of ``class_names``.

    Boxes of classes not in ``class_names`` and hard negatives are dropped.
    """
    class_to_id = {name: i for i, name in enumerate(class_names)}
    coco_images, coco_anns = [], []
    ann_id = 1
    for img in images:
        coco_images.append({"id": img.id, "file_name": image_file_name(img), "width": img.width, "height": img.height})
        for a in img.annotations:
            if a.class_name not in class_to_id or a.type == "hard_negative":
                continue
            x, y, w, h = xyxy_to_xywh((a.x1, a.y1, a.x2, a.y2))
            if w < 1 or h < 1:
                continue
            coco_anns.append({
                "id": ann_id,
                "image_id": img.id,
                "category_id": class_to_id[a.class_name] + 1,
                "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                "area": round(w * h, 2),
                "iscrowd": 0,
            })
            ann_id += 1
    return {
        "info": {"description": "object-detection dataset snapshot", "date_created": datetime.now(timezone.utc).isoformat()},
        "images": coco_images,
        "annotations": coco_anns,
        "categories": coco_categories(class_names),
    }


def split_stats(coco: dict) -> dict:
    names = [c["name"] for c in sorted(coco["categories"], key=lambda c: c["id"])]
    per_class = {name: 0 for name in names}
    with_boxes = set()
    for a in coco["annotations"]:
        per_class[names[a["category_id"] - 1]] += 1
        with_boxes.add(a["image_id"])
    return {
        "images": len(coco["images"]),
        "negative_images": len(coco["images"]) - len(with_boxes),
        "boxes": len(coco["annotations"]),
        "boxes_per_class": per_class,
    }


def create_snapshot(session: Session, s3: ObjectStorage, run_id: int, local_root: str, class_names: list[str]) -> Snapshot:
    # row lock until the links are committed: a concurrent delete waits and then only hides the image
    labeled = list(
        session.execute(
            select(Image)
            .where(Image.annotation_status == AnnotationStatus.labeled, Image.deleted_at.is_(None))
            .options(selectinload(Image.annotations))
            .order_by(Image.id)
            .with_for_update(of=Image)
        ).scalars()
    )
    reviewed = [i for i in labeled if is_reviewed_for(i.reviewed_classes, class_names)]
    excluded = len(labeled) - len(reviewed)
    if excluded:
        log.warning("%d labeled images were not checked for all classes %s and are excluded", excluded, class_names)
    # empty images marked as visually identical to another one would over-represent that scene
    images = [i for i in reviewed if i.duplicate_of is None]
    duplicates = len(reviewed) - len(images)
    if duplicates:
        log.info("%d duplicate empty images are excluded", duplicates)
    ratio = float(get_setting(session, "validation_ratio"))
    for img in images:
        if img.dataset_split is None:
            img.dataset_split = DatasetSplit(assign_split(img.sha256, ratio))

    by_split = {s: [i for i in images if i.dataset_split == s] for s in SPLIT_FILES}
    if not by_split[DatasetSplit.train]:
        session.commit()
        raise RuntimeError(f"dataset has no usable labeled training images for classes {class_names}")
    if not by_split[DatasetSplit.validation]:
        session.commit()
        raise RuntimeError(f"dataset has no usable labeled validation images for classes {class_names}")
    link_images(session, run_id, (i.id for i in images))
    session.commit()

    prefix = f"{run_id}/"
    bucket_ds = s3.settings.bucket_datasets
    bucket_img = s3.settings.bucket_images
    local_dir = os.path.join(local_root, "dataset")
    os.makedirs(os.path.join(local_dir, "annotations"), exist_ok=True)
    os.makedirs(os.path.join(local_dir, "images"), exist_ok=True)

    def download(img: Image) -> None:  # straight from the image library, no copy in the datasets bucket
        s3.download_file(bucket_img, img.s3_object_key, os.path.join(local_dir, "images", image_file_name(img)))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(download, images))

    stats: dict = {"classes": list(class_names), "excluded_needs_review": excluded, "excluded_duplicates": duplicates}
    cocos = {split: build_coco(by_split[split], class_names) for split in SPLIT_FILES}
    for split in SPLIT_FILES:
        stats[split.value] = split_stats(cocos[split])

    hn_records, crop_stats = add_hard_negative_crops(session, cocos[DatasetSplit.train], images, class_names, local_dir)
    stats["hard_negatives"] = crop_stats
    for record in hn_records:
        if record.get("crop_file"):
            s3.upload_file(bucket_ds, f"{prefix}images/{record['crop_file']}",
                           os.path.join(local_dir, "images", record["crop_file"]), "image/jpeg")

    for split, file_name in SPLIT_FILES.items():
        path = os.path.join(local_dir, "annotations", file_name)
        with open(path, "w") as f:
            json.dump(cocos[split], f)
        s3.upload_file(bucket_ds, f"{prefix}annotations/{file_name}", path, "application/json")
    path = os.path.join(local_dir, "annotations", "hard_negatives.json")
    with open(path, "w") as f:
        json.dump(hn_records, f)
    s3.upload_file(bucket_ds, f"{prefix}annotations/hard_negatives.json", path, "application/json")

    manifest = {
        "training_run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classes": list(class_names),
        "excluded_needs_review": excluded,
        "excluded_duplicates": duplicates,
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
                "boxes": sum(1 for a in i.annotations if a.class_name in class_names and a.type != "hard_negative"),
                "hard_negatives": sum(1 for a in i.annotations if a.class_name in class_names and a.type == "hard_negative"),
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


def add_hard_negative_crops(session: Session, train_coco: dict, images: list[Image], class_names: list[str],
                            local_dir: str) -> tuple[list[dict], dict]:
    """Append hard-negative crops of training images to ``train_coco`` (in place).

    Returns one record per hard negative of the run's classes (train and
    validation images; used for the regression check) and statistics.
    """
    factor = float(get_setting(session, "hard_negative_context_factor"))
    min_fraction = float(get_setting(session, "hard_negative_min_crop_fraction"))
    oversample = int(get_setting(session, "hard_negative_oversample"))
    class_to_id = {name: i for i, name in enumerate(class_names)}
    next_image_id = max((im["id"] for im in train_coco["images"]), default=0) + 1
    next_ann_id = max((a["id"] for a in train_coco["annotations"]), default=0) + 1
    records: list[dict] = []
    crops = 0
    per_class = {name: 0 for name in class_names}

    for img in images:
        positives = [(a.class_name, a.x1, a.y1, a.x2, a.y2) for a in img.annotations
                     if a.type != "hard_negative" and a.class_name in class_to_id]
        for hn in img.annotations:
            if hn.type != "hard_negative" or hn.class_name not in class_to_id:
                continue
            per_class[hn.class_name] += 1
            record = {
                "annotation_id": hn.id,
                "image_id": img.id,
                "file_name": image_file_name(img),
                "split": img.dataset_split.value,
                "class": hn.class_name,
                "bbox": [hn.x1, hn.y1, hn.x2, hn.y2],
                "source_model": hn.source_model,
                "source_confidence": hn.source_confidence,
            }
            records.append(record)
            if img.dataset_split != DatasetSplit.train or oversample <= 0:
                continue
            crop = compute_crop(img.width, img.height, (hn.x1, hn.y1, hn.x2, hn.y2), factor, min_fraction)
            boxes = transform_boxes(positives, crop)
            crop_file = f"hn_{hn.id}.jpg"
            write_crop(os.path.join(local_dir, "images", image_file_name(img)), crop, os.path.join(local_dir, "images", crop_file))
            record.update(crop_file=crop_file, crop=[crop.x1, crop.y1, crop.x2, crop.y2], positives_in_crop=len(boxes))
            crops += 1
            for _ in range(oversample):  # oversampling = repeated image entries
                train_coco["images"].append({"id": next_image_id, "file_name": crop_file, "width": crop.width,
                                             "height": crop.height, "hard_negative_of": hn.id})
                for cls, x1, y1, x2, y2 in boxes:
                    w, h = x2 - x1, y2 - y1
                    train_coco["annotations"].append({
                        "id": next_ann_id, "image_id": next_image_id, "category_id": class_to_id[cls] + 1,
                        "bbox": [round(x1, 2), round(y1, 2), round(w, 2), round(h, 2)], "area": round(w * h, 2), "iscrowd": 0,
                    })
                    next_ann_id += 1
                next_image_id += 1

    stats = {
        "total": len(records),
        "per_class": per_class,
        "train_crops": crops,
        "oversample": oversample,
        "context_factor": factor,
        "min_crop_fraction": min_fraction,
    }
    if records:
        log.info("hard negatives: %s", json.dumps(stats))
    return records, stats


def load_hard_negatives(local_dir: str) -> list[dict]:
    path = os.path.join(local_dir, "annotations", "hard_negatives.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def load_val_samples(local_dir: str) -> tuple[dict, list[dict]]:
    """Return the COCO val dict and per-image samples with absolute image paths."""
    with open(os.path.join(local_dir, "annotations", "val.json")) as f:
        coco = json.load(f)
    samples = [
        {"id": im["id"], "path": os.path.join(local_dir, "images", im["file_name"]), "width": im["width"], "height": im["height"]}
        for im in coco["images"]
    ]
    return coco, samples


def current_validation_set(session: Session, s3: ObjectStorage, local_root: str, class_names: list[str]) -> str | None:
    """Download the current labeled validation images (COCO bootstrap model, benchmark of all models).

    Also writes ``annotations/hard_negatives.json`` with the hard negatives of these images (regression check).
    """
    candidates = list(
        session.execute(
            select(Image)
            .where(Image.annotation_status == AnnotationStatus.labeled, Image.dataset_split == DatasetSplit.validation,
                   Image.deleted_at.is_(None))
            .options(selectinload(Image.annotations))
        ).scalars()
    )
    images = [i for i in candidates if is_reviewed_for(i.reviewed_classes, class_names)]
    if not images:
        return None
    local_dir = os.path.join(local_root, "val-current")
    os.makedirs(os.path.join(local_dir, "annotations"), exist_ok=True)
    with open(os.path.join(local_dir, "annotations", "val.json"), "w") as f:
        json.dump(build_coco(images, class_names), f)
    hard_negatives = [
        {"annotation_id": a.id, "image_id": img.id, "file_name": image_file_name(img), "split": DatasetSplit.validation.value,
         "class": a.class_name, "bbox": [a.x1, a.y1, a.x2, a.y2], "source_model": a.source_model,
         "source_confidence": a.source_confidence}
        for img in images for a in img.annotations if a.type == "hard_negative" and a.class_name in class_names
    ]
    with open(os.path.join(local_dir, "annotations", "hard_negatives.json"), "w") as f:
        json.dump(hard_negatives, f)
    for img in images:
        s3.download_file(s3.settings.bucket_images, img.s3_object_key, os.path.join(local_dir, "images", image_file_name(img)))
    return local_dir
