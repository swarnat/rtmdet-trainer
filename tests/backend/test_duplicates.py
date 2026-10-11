"""Duplicate check of empty images."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import Annotation, Image, ImageSuggestion

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services.duplicates import FP_HEIGHT, FP_WIDTH, find_duplicates, fingerprint

from conftest import FakeStorage


def scene(seed: int) -> np.ndarray:
    """Smooth random 'camera view' at fingerprint size."""
    small = np.random.default_rng(seed).integers(0, 255, (9, 16), dtype=np.uint8)
    return cv2.resize(small, (FP_WIDTH, FP_HEIGHT), interpolation=cv2.INTER_CUBIC)


def fp(img: np.ndarray) -> bytes:
    return np.clip(img, 0, 255).astype(np.uint8).tobytes()


def test_find_duplicates_same_view_only_without_changes():
    base = scene(1).astype(np.int16)
    noise = np.random.default_rng(2).integers(-3, 4, base.shape)
    with_object = base.copy()
    with_object[40:50, 60:68] = 255           # something appeared
    small_change = base.copy()
    small_change[30:36, 16:24] += 12          # e.g. a tree moved a little
    timestamp_changed = base.copy()
    timestamp_changed[0:5, 0:60] = 0          # overlay band is ignored
    images = [
        (1, fp(base)),
        (2, fp(base + noise)),                 # duplicate of 1
        (3, fp(with_object)),
        (4, fp(base - 40)),                    # same scene, other lighting: kept
        (5, fp(scene(7))),                     # other camera
        (6, fp(timestamp_changed)),            # duplicate of 1
        (7, fp(with_object + noise)),          # duplicate of 3
        (8, fp(small_change)),
    ]
    found = find_duplicates(images, 0.12)
    assert {k: v[0] for k, v in found.items()} == {2: 1, 6: 1, 7: 3}
    assert found[6][1] == 0.0 and 0 < found[2][1] < 0.12
    # a looser threshold also takes the small change; kept images are never marked
    assert find_duplicates(images, 0.5)[8][0] == 1
    assert 2 not in find_duplicates(images, 0.12, keep={2})


def test_fingerprint_from_thumbnail():
    jpeg = cv2.imencode(".jpg", np.full((216, 384, 3), 120, np.uint8))[1].tobytes()
    assert len(fingerprint(jpeg)) == FP_WIDTH * FP_HEIGHT


@pytest.fixture()
def client(session_factory):
    jpeg = cv2.imencode(".jpg", cv2.cvtColor(scene(3), cv2.COLOR_GRAY2BGR))[1].tobytes()
    same = fingerprint(jpeg)
    with session_factory() as s:
        def add(i, status, fingerprint=same, **kw):
            s.add(Image(id=i, s3_object_key=f"images/{i}.jpg", sha256=f"{i:064d}", content_type="image/jpeg",
                        size_bytes=1, width=1920, height=1080, annotation_status=status, fingerprint=fingerprint,
                        reviewed_classes=["person"] if status == "labeled" else None, **kw))
        add(1, "unlabeled")                       # batch test found nothing
        add(2, "labeled")                         # negative
        add(3, "unlabeled")                       # batch test found something
        add(4, "unlabeled")                       # no batch test yet
        add(5, "labeled")                         # has a box
        add(6, "unlabeled", fingerprint=None)     # empty, fingerprint computed from the thumbnail
        s.flush()
        for i, dets in ((1, []), (3, [{"class": "person", "confidence": 0.5, "bbox": {"x1": 1, "y1": 1, "x2": 9, "y2": 9}}]), (6, [])):
            s.add(ImageSuggestion(image_id=i, model_version="m", input_width=1536, input_height=864, confidence=0.25,
                                  detections_json=dets))
        s.add(Annotation(image_id=5, class_name="person", x1=1, y1=1, x2=50, y2=50, type="positive", source="manual"))
        s.commit()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: FakeStorage(jpeg)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_check_marks_only_empty_images_labeled_first(client):
    res = client.post("/api/v1/images/duplicates/check").json()
    assert res == {"checked": 3, "duplicates": 2, "fingerprints_computed": 1, "failed": 0}
    items = client.get("/api/v1/images", params={"duplicate": "true"}).json()["items"]
    # the labeled negative stays, the empty open images are its duplicates
    assert [(i["id"], i["duplicate_of"]) for i in items] == [(1, 2), (6, 2)]
    assert client.get("/api/v1/images/1/neighbours", params={"duplicate": "true"}).json() == {"previous": None, "next": 6}
    assert client.get("/api/v1/images/stats").json()["images_duplicates"] == 2


def test_annotating_the_original_clears_marks(client):
    client.post("/api/v1/images/duplicates/check")
    client.put("/api/v1/images/2/annotations", json={"annotations": [
        {"class": "person", "x1": 10, "y1": 10, "x2": 60, "y2": 90}]})
    assert client.get("/api/v1/images", params={"duplicate": "true"}).json()["total"] == 0
    # next check: image 1 is now the original of the empty group
    client.post("/api/v1/images/duplicates/check")
    assert [(i["id"], i["duplicate_of"]) for i in client.get("/api/v1/images", params={"duplicate": "true"}).json()["items"]] == [(6, 1)]


def test_groups_and_review_decisions(client):
    client.post("/api/v1/images/duplicates/check")
    groups = client.get("/api/v1/images/duplicates/groups").json()
    assert [(g["original"]["id"], [d["id"] for d in g["duplicates"]]) for g in groups] == [(2, [1, 6])]
    assert groups[0]["duplicates"][0]["duplicate_score"] == 0.0

    storage = app.dependency_overrides[get_storage]()
    storage.delete = lambda bucket, key: None
    app.dependency_overrides[get_storage] = lambda: storage
    assert client.post("/api/v1/images/duplicates/resolve", json={"keep": [1], "delete": [1]}).status_code == 422
    assert client.post("/api/v1/images/duplicates/resolve", json={"keep": [1], "delete": [6]}).json() == {"kept": 1, "deleted": 1}
    assert sorted(i["id"] for i in client.get("/api/v1/images").json()["items"]) == [1, 2, 3, 4, 5]
    # the kept image stays unmarked in later checks
    client.post("/api/v1/images/duplicates/check")
    detail = client.get("/api/v1/images/1").json()
    assert (detail["duplicate_of"], detail["duplicate_keep"]) == (None, True)
    assert client.get("/api/v1/images/duplicates/groups").json() == []
