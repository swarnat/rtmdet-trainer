"""Snapshots link images (link count like nlink) instead of copying them; deleting a linked image only hides it."""
from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import Annotation, AnnotationStatus, Image, ModelStatus, ModelVersion, SnapshotImage, TrainingRun, TrainingStatus
from odcore.snapshots import convert_legacy_snapshots, link_images, release_snapshot, release_unneeded_snapshots

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app


class MemoryStorage:
    class settings:  # noqa: N801 - mimics S3Settings attributes
        bucket_images = "training-images"
        bucket_datasets = "datasets"
        bucket_models = "models"

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_bytes(self, bucket, key, data, content_type="application/octet-stream"):
        self.objects[(bucket, key)] = data

    def get_bytes(self, bucket, key):
        return self.objects[(bucket, key)]

    def delete(self, bucket, key):
        self.objects.pop((bucket, key), None)

    def list_keys(self, bucket, prefix):
        return [k for b, k in sorted(self.objects) if b == bucket and k.startswith(prefix)]

    def delete_prefix(self, bucket, prefix):
        keys = self.list_keys(bucket, prefix)
        for k in keys:
            self.delete(bucket, k)
        return len(keys)

    def keys(self, bucket):
        return sorted(k for b, k in self.objects if b == bucket)


@pytest.fixture()
def storage():
    return MemoryStorage()


@pytest.fixture()
def client(session_factory, storage):
    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: storage
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_image(session, storage, n: int, labeled: bool = True) -> int:
    sha = f"{n:064x}"
    img = Image(s3_object_key=f"images/{sha[:2]}/{sha}.jpg", thumbnail_key=f"thumbnails/{sha[:2]}/{sha}.jpg", sha256=sha,
                content_type="image/jpeg", size_bytes=1, width=640, height=360,
                annotation_status=AnnotationStatus.labeled if labeled else AnnotationStatus.unlabeled)
    img.annotations = [Annotation(class_name="person", x1=1, y1=1, x2=50, y2=50)]
    session.add(img)
    session.commit()
    storage.put_bytes("training-images", img.s3_object_key, b"jpeg")
    storage.put_bytes("training-images", img.thumbnail_key, b"thumb")
    return img.id


def add_run(session, storage, image_ids, status=TrainingStatus.completed, with_model=True) -> int:
    run = TrainingRun(base_model_id="rtmdet-s-coco", status=status, input_width=640, input_height=384, epochs=1,
                      batch_size=1)
    session.add(run)
    session.commit()
    run.dataset_snapshot = f"datasets/{run.id}/"
    link_images(session, run.id, image_ids)
    if with_model:
        mv = ModelVersion(version=f"model-{run.id:04d}", status=ModelStatus.candidate, checkpoint_key="x", onnx_key="x",
                          openvino_key=f"model-{run.id:04d}/openvino/model.xml", input_width=640, input_height=384,
                          class_names=["person"], training_run_id=run.id)
        session.add(mv)
        session.flush()
        run.model_version_id = mv.id
    session.commit()
    storage.put_bytes("datasets", f"{run.id}/manifest.json", b"{}")
    storage.put_bytes("datasets", f"{run.id}/images/hn_1.jpg", b"crop")
    return run.id


def refs(session, image_id):
    session.expire_all()
    return session.get(Image, image_id).snapshot_refs


def test_link_count_follows_snapshots(session_factory, storage):
    with session_factory() as s:
        a, b = add_image(s, storage, 1), add_image(s, storage, 2)
        r1 = add_run(s, storage, [a, b])
        r2 = add_run(s, storage, [a])
        assert (refs(s, a), refs(s, b)) == (2, 1)

        assert release_snapshot(s, storage, r1) == 2
        assert (refs(s, a), refs(s, b)) == (1, 0)
        assert storage.list_keys("datasets", f"{r1}/") == []  # manifest, annotations, hn crops
        assert storage.list_keys("datasets", f"{r2}/") != []
        assert s.get(TrainingRun, r1).dataset_snapshot is None

        # idempotent: a second release does not decrement again
        assert release_snapshot(s, storage, r1) == 0
        assert refs(s, a) == 1


def test_deleting_a_linked_image_only_hides_it(client, session_factory, storage):
    with session_factory() as s:
        img = add_image(s, storage, 1)
        free = add_image(s, storage, 2)
        run = add_run(s, storage, [img])

    assert client.get(f"/api/v1/images/{img}").json()["snapshot_refs"] == 1
    assert client.delete(f"/api/v1/images/{img}").status_code == 204
    assert client.delete(f"/api/v1/images/{free}").status_code == 204

    # hidden everywhere in the UI/API ...
    assert client.get(f"/api/v1/images/{img}").status_code == 404
    assert client.get("/api/v1/images").json()["total"] == 0
    stats = client.get("/api/v1/images/stats").json()
    assert stats["images_total"] == 0 and stats["images_retained_for_snapshots"] == 1
    # ... but its file stays for the snapshot; the unreferenced image is gone completely
    assert storage.keys("training-images") == sorted([f"images/00/{1:064x}.jpg", f"thumbnails/00/{1:064x}.jpg"])
    with session_factory() as s:
        hidden = s.get(Image, img)
        assert hidden.deleted_at is not None and hidden.annotations == [] and hidden.snapshot_refs == 1
        assert s.get(Image, free) is None

        # last link released (e.g. model deleted) -> row and files are purged
        release_snapshot(s, storage, run)
        s.expire_all()
        assert s.get(Image, img) is None
    assert storage.keys("training-images") == []


def test_deleting_a_model_releases_its_snapshot(client, session_factory, storage):
    with session_factory() as s:
        img = add_image(s, storage, 1)
        run = add_run(s, storage, [img])
    client.delete(f"/api/v1/images/{img}")

    assert client.delete(f"/api/v1/models/model-{run:04d}").status_code == 204

    with session_factory() as s:
        assert s.get(Image, img) is None
        assert s.query(SnapshotImage).count() == 0
    assert storage.keys("datasets") == [] and storage.keys("training-images") == []


def test_reupload_restores_a_hidden_image(client, session_factory, storage):
    ok, buf = cv2.imencode(".jpg", np.full((90, 160, 3), 80, np.uint8))
    data = buf.tobytes()
    first = client.post("/api/v1/images", files=[("files", ("a.jpg", data, "image/jpeg"))]).json()[0]
    image_id = first["image"]["id"]
    with session_factory() as s:
        add_run(s, storage, [image_id])
    client.delete(f"/api/v1/images/{image_id}")

    again = client.post("/api/v1/images", files=[("files", ("b.jpg", data, "image/jpeg"))]).json()[0]

    assert again["status"] == "created" and again["image"]["id"] == image_id
    detail = client.get(f"/api/v1/images/{image_id}").json()
    assert detail["annotation_status"] == "unlabeled" and detail["snapshot_refs"] == 1


def test_sweep_releases_failed_runs_and_deleted_models(session_factory, storage):
    with session_factory() as s:
        img = add_image(s, storage, 1)
        keep = add_run(s, storage, [img])
        failed = add_run(s, storage, [img], status=TrainingStatus.failed, with_model=False)
        orphan = add_run(s, storage, [img], with_model=False)  # completed, model deleted
        running = add_run(s, storage, [img], status=TrainingStatus.running, with_model=False)
        assert refs(s, img) == 4

        assert release_unneeded_snapshots(s, storage) == 2

        assert refs(s, img) == 2
        linked = {r for (r,) in s.query(SnapshotImage.training_run_id)}
        assert linked == {keep, running} and failed not in linked and orphan not in linked


def test_convert_legacy_snapshot_with_image_copies(session_factory, storage):
    with session_factory() as s:
        a, b = add_image(s, storage, 1), add_image(s, storage, 2)
        run = TrainingRun(base_model_id="rtmdet-s-coco", status=TrainingStatus.completed, input_width=640,
                          input_height=384, epochs=1, batch_size=1, dataset_snapshot="datasets/1/")
        s.add(run)
        s.commit()
        mv = ModelVersion(version="model-0001", status=ModelStatus.candidate, checkpoint_key="x", onnx_key="x",
                          openvino_key="m/model.xml", input_width=640, input_height=384, class_names=["person"])
        s.add(mv)
        s.flush()
        run.model_version_id = mv.id
        s.commit()
        sha_a, sha_b, sha_gone = f"{1:064x}", f"{2:064x}", f"{99:064x}"
        manifest = {"images": [{"id": a, "sha256": sha_a}, {"id": b, "sha256": sha_b}, {"id": 99, "sha256": sha_gone}]}
        storage.put_bytes("datasets", f"{run.id}/manifest.json", json.dumps(manifest).encode())
        for sha in (sha_a, sha_b, sha_gone):
            storage.put_bytes("datasets", f"{run.id}/images/{sha}.jpg", b"copy")
        storage.put_bytes("datasets", f"{run.id}/images/hn_5.jpg", b"crop")

        stats = convert_legacy_snapshots(s, storage)

        assert stats == {"linked_runs": 1, "links": 2, "copies_removed": 2, "copies_kept": 1}
        assert (refs(s, a), refs(s, b)) == (1, 1)
        # the copy of an image that no longer exists in the library is its only file: kept
        assert storage.list_keys("datasets", f"{run.id}/images/") == [f"{run.id}/images/{sha_gone}.jpg", f"{run.id}/images/hn_5.jpg"]
        # idempotent
        assert convert_legacy_snapshots(s, storage)["links"] == 0
        assert refs(s, a) == 1
