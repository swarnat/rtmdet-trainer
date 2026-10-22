"""Annotation review: crops of annotated boxes per class."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import Annotation, DatasetSplit, Image, utcnow

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services.annotation_crops import crop_jpeg, crop_window, decoded_cache

from conftest import FakeStorage


def test_crop_window_adds_margin_and_clips():
    assert crop_window(100, 50, 200, 150, 1920, 1080) == (80, 30, 220, 170)
    assert crop_window(5, 5, 1910, 1075, 1920, 1080) == (0, 0, 1920, 1080)


def test_crop_jpeg_size_and_downscale():
    image = np.zeros((1080, 1920, 3), np.uint8)
    small = cv2.imdecode(np.frombuffer(crop_jpeg(image, (100, 50, 140, 130)), np.uint8), cv2.IMREAD_COLOR)
    assert small.shape[:2] == (120, 80)  # 80x40 box + 2x20 margin
    big = cv2.imdecode(np.frombuffer(crop_jpeg(image, (0, 0, 1000, 500)), np.uint8), cv2.IMREAD_COLOR)
    assert max(big.shape[:2]) == 320


@pytest.fixture()
def client(session_factory):
    ok, buf = cv2.imencode(".jpg", np.full((1080, 1920, 3), 128, np.uint8))
    storage = FakeStorage(buf.tobytes())
    with session_factory() as s:
        live = Image(s3_object_key="a.jpg", sha256="a" * 64, content_type="image/jpeg", size_bytes=1, width=1920, height=1080,
                     dataset_split=DatasetSplit.validation)
        gone = Image(s3_object_key="b.jpg", sha256="b" * 64, content_type="image/jpeg", size_bytes=1, width=1920, height=1080,
                     deleted_at=utcnow())
        s.add_all([live, gone])
        s.flush()
        s.add_all([
            Annotation(image_id=live.id, class_name="person", x1=100, y1=100, x2=140, y2=200),  # 40x100
            Annotation(image_id=live.id, class_name="person", x1=300, y1=300, x2=500, y2=350, reflected=True),  # 200x50, lying
            Annotation(image_id=live.id, class_name="person", x1=600, y1=300, x2=650, y2=350, type="hard_negative"),
            Annotation(image_id=live.id, class_name="vehicle", x1=0, y1=0, x2=300, y2=200),
            Annotation(image_id=gone.id, class_name="person", x1=0, y1=0, x2=10, y2=10),
        ])
        s.commit()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: storage
    decoded_cache._items.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_class_counts_skip_deleted_images(client):
    res = client.get("/api/v1/annotations/review/classes").json()
    zero = {"positive": 0, "hard_negative": 0, "ignore": 0, "positive_reflected": 0, "hard_negative_reflected": 0, "ignore_reflected": 0}
    assert res == [
        {"class": "person", **zero, "positive": 2, "hard_negative": 1, "positive_reflected": 1},
        {"class": "vehicle", **zero, "positive": 1},
    ]


def test_reflected_filter(client):
    res = client.get("/api/v1/annotations/review", params={"class": "person", "reflected": True}).json()
    assert res["total"] == 1 and res["items"][0]["reflected"] is True and res["items"][0]["x2"] - res["items"][0]["x1"] == 200
    assert client.get("/api/v1/annotations/review", params={"class": "person", "reflected": True, "type": "hard_negative"}).json()["total"] == 0
    assert client.get("/api/v1/annotations/review", params={"class": "person"}).json()["total"] == 2


def test_list_filters_and_sorts(client):
    res = client.get("/api/v1/annotations/review", params={"class": "person", "sort": "widest"}).json()
    assert res["total"] == 2 and res["margin"] == 20
    assert [(i["x2"] - i["x1"]) for i in res["items"]] == [200, 40]
    assert res["items"][0]["dataset_split"] == "validation"
    hn = client.get("/api/v1/annotations/review", params={"class": "person", "type": "hard_negative"}).json()
    assert hn["total"] == 1
    assert client.get("/api/v1/annotations/review", params={"class": "person", "split": "train"}).json()["total"] == 0


def test_crop_endpoint(client):
    item = client.get("/api/v1/annotations/review", params={"class": "person", "sort": "tallest"}).json()["items"][0]
    res = client.get(f"/api/v1/annotations/{item['id']}/crop")
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"
    crop = cv2.imdecode(np.frombuffer(res.content, np.uint8), cv2.IMREAD_COLOR)
    assert crop.shape[:2] == (140, 80)
    assert client.get("/api/v1/annotations/99999/crop").status_code == 404
