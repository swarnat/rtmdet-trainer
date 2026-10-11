"""Snapshots link the images (no copies in the datasets bucket); hard-negative crops are still stored per run."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import cv2
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from odcore.db import (Annotation, AnnotationStatus, Base, DatasetSplit, Image, SnapshotImage, TrainingRun, TrainingStatus,
                       utcnow)
from trainer.dataset import create_snapshot


class MemoryStorage:
    class settings:  # noqa: N801 - mimics S3Settings attributes
        bucket_images = "training-images"
        bucket_datasets = "datasets"

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def download_file(self, bucket, key, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(self.objects[(bucket, key)])

    def upload_file(self, bucket, key, path, content_type=None):
        with open(path, "rb") as f:
            self.objects[(bucket, key)] = f.read()

    def copy(self, *args):  # must not be used any more
        raise AssertionError("snapshot must not copy images")

    def keys(self, bucket):
        return sorted(k for b, k in self.objects if b == bucket)


def test_snapshot_links_images_instead_of_copying(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    storage = MemoryStorage()
    ok, jpeg = cv2.imencode(".jpg", np.full((360, 640, 3), 90, np.uint8))

    ids = []
    for n, split in enumerate([DatasetSplit.train, DatasetSplit.train, DatasetSplit.validation], start=1):
        sha = f"{n:064x}"
        img = Image(s3_object_key=f"images/{sha[:2]}/{sha}.jpg", sha256=sha, content_type="image/jpeg", size_bytes=1,
                    width=640, height=360, annotation_status=AnnotationStatus.labeled, dataset_split=split,
                    reviewed_classes=["person"])
        img.annotations = [Annotation(class_name="person", x1=10, y1=10, x2=100, y2=200)]
        if n == 1:
            img.annotations.append(Annotation(class_name="person", type="hard_negative", x1=300, y1=50, x2=360, y2=120))
        session.add(img)
        session.commit()
        storage.objects[("training-images", img.s3_object_key)] = jpeg.tobytes()
        ids.append(img.id)
    hidden = Image(s3_object_key="images/ff/hidden.jpg", sha256="f" * 64, content_type="image/jpeg", size_bytes=1,
                   width=640, height=360, annotation_status=AnnotationStatus.labeled, dataset_split=DatasetSplit.train,
                   reviewed_classes=["person"], deleted_at=utcnow())
    session.add(hidden)
    # empty labeled image marked as duplicate of another one: not used for training
    duplicate = Image(s3_object_key="images/ee/dup.jpg", sha256="e" * 64, content_type="image/jpeg", size_bytes=1,
                      width=640, height=360, annotation_status=AnnotationStatus.labeled, dataset_split=DatasetSplit.train,
                      reviewed_classes=["person"], duplicate_of=ids[0])
    session.add(duplicate)
    run = TrainingRun(base_model_id="rtmdet-s-coco", status=TrainingStatus.running, input_width=640, input_height=384,
                      epochs=1, batch_size=1)
    session.add(run)
    session.commit()

    snapshot = create_snapshot(session, storage, run.id, str(tmp_path), ["person"])

    # images are linked (link count 1), deleted-but-retained images are not used
    assert sorted(i for (i,) in session.query(SnapshotImage.image_id)) == ids
    assert [session.get(Image, i).snapshot_refs for i in ids] == [1, 1, 1]
    assert session.get(Image, hidden.id).snapshot_refs == 0
    assert session.get(Image, duplicate.id).snapshot_refs == 0
    assert snapshot.manifest["excluded_duplicates"] == 1
    # datasets bucket: annotations, manifest and the hard-negative crop - no image copies
    assert storage.keys("datasets") == [
        f"{run.id}/annotations/hard_negatives.json", f"{run.id}/annotations/train.json", f"{run.id}/annotations/val.json",
        f"{run.id}/images/hn_{session.get(Image, ids[0]).annotations[1].id}.jpg", f"{run.id}/manifest.json",
    ]
    # the images are available locally for the training
    assert sorted(os.listdir(os.path.join(snapshot.local_dir, "images"))) == sorted(
        [f"{1:064x}.jpg", f"{2:064x}.jpg", f"{3:064x}.jpg", f"hn_{session.get(Image, ids[0]).annotations[1].id}.jpg"])
    assert snapshot.manifest["images"][0]["source_key"] == f"images/00/{1:064x}.jpg"


def test_current_validation_set_includes_its_hard_negatives(tmp_path):
    import json

    from trainer.dataset import current_validation_set, load_hard_negatives, load_val_samples

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    storage = MemoryStorage()
    ok, jpeg = cv2.imencode(".jpg", np.full((360, 640, 3), 90, np.uint8))
    for n, split in enumerate([DatasetSplit.validation, DatasetSplit.train], start=1):
        sha = f"{n:064x}"
        img = Image(s3_object_key=f"images/{sha}.jpg", sha256=sha, content_type="image/jpeg", size_bytes=1, width=640,
                    height=360, annotation_status=AnnotationStatus.labeled, dataset_split=split, reviewed_classes=["person"])
        img.annotations = [Annotation(class_name="person", x1=10, y1=10, x2=100, y2=200),
                           Annotation(class_name="person", type="hard_negative", x1=300, y1=50, x2=360, y2=120)]
        session.add(img)
        storage.objects[("training-images", img.s3_object_key)] = jpeg.tobytes()
    session.commit()

    local = current_validation_set(session, storage, str(tmp_path), ["person"])
    coco, samples = load_val_samples(local)
    hns = load_hard_negatives(local)
    assert len(samples) == 1 and len(coco["annotations"]) == 1      # train image and hard negatives not in val.json
    assert [(h["split"], h["class"], h["bbox"]) for h in hns] == [("validation", "person", [300, 50, 360, 120])]


def test_benchmark_reports_validation_images_seen_in_training(tmp_path):
    import json

    from trainer.benchmark import _seen_in_training

    storage = MemoryStorage()
    manifest = {"images": [{"id": 1, "split": "train"}, {"id": 2, "split": "train"}, {"id": 3, "split": "validation"}]}
    storage.objects[("datasets", "7/manifest.json")] = json.dumps(manifest).encode()
    # images 2 and 3 are validation images today; image 2 was a training image of run 7
    assert _seen_in_training(storage, 7, {2, 3}, str(tmp_path)) == 1
    assert _seen_in_training(storage, None, {2, 3}, str(tmp_path)) == 0      # imported model
    assert _seen_in_training(storage, 8, {2, 3}, str(tmp_path)) is None      # snapshot gone: unknown
