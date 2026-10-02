"""End-to-end tests against a running stack (docker compose up -d).

    OD_BASE_URL=http://localhost:8080 pytest tests/integration

Skipped when OD_BASE_URL is not set. Needs a production model (the COCO
bootstrap model is imported automatically on first start).
"""
from __future__ import annotations

import os
import urllib.request

import cv2
import httpx
import numpy as np
import pytest

BASE = os.environ.get("OD_BASE_URL")
pytestmark = pytest.mark.skipif(not BASE, reason="OD_BASE_URL not set")
DEMO_URL = "https://raw.githubusercontent.com/open-mmlab/mmdetection/v3.3.0/demo/demo.jpg"


@pytest.fixture(scope="module")
def api():
    with httpx.Client(base_url=BASE.rstrip("/") + "/api/v1", timeout=120) as client:
        yield client


@pytest.fixture(scope="module")
def street_image() -> bytes:
    """A 16:9 street scene (MMDetection demo image, letterboxed to 16:9)."""
    data = urllib.request.urlopen(DEMO_URL, timeout=30).read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    canvas = np.zeros((h, int(h * 16 / 9), 3), np.uint8)
    canvas[:, :w] = img
    canvas = cv2.resize(canvas, (1920, 1080))
    return cv2.imencode(".jpg", canvas)[1].tobytes()


def test_health(api):
    assert api.get("/health").json()["status"] == "ok"


def test_detect_street_scene(api, street_image):
    res = api.post("/detect", files={"image": ("street.jpg", street_image, "image/jpeg")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["image"] == {"width": 1920, "height": 1080}
    classes = {d["class"] for d in body["detections"]}
    assert "vehicle" in classes
    for d in body["detections"]:
        b = d["bbox"]
        assert 0 <= b["x1"] < b["x2"] <= 1920 and 0 <= b["y1"] < b["y2"] <= 1080


def test_upload_annotate_negative_and_predict(api, street_image):
    up = api.post("/images", files=[("files", ("street.jpg", street_image, "image/jpeg"))]).json()[0]
    assert up["status"] in ("created", "duplicate")
    image_id = up["image"]["id"]

    pred = api.post(f"/images/{image_id}/detect", data={"confidence": "0.3"}).json()
    boxes = [{"class": d["class"], **d["bbox"], "source": "prediction"} for d in pred["detections"]]
    saved = api.put(f"/images/{image_id}/annotations", json={"annotations": boxes}).json()
    assert saved["annotation_status"] == "labeled"
    assert len(saved["annotations"]) == len(boxes)

    # an all-black image saved without boxes is a valid negative example
    black = cv2.imencode(".png", np.full((1080, 1920, 3), 3, np.uint8))[1].tobytes()
    neg = api.post("/images", files=[("files", ("black.png", black, "image/png"))]).json()[0]["image"]
    saved = api.put(f"/images/{neg['id']}/annotations", json={"annotations": []}).json()
    assert saved["annotation_status"] == "labeled" and saved["annotations"] == []
    negatives = api.get("/images", params={"negative": "true"}).json()["items"]
    assert any(i["id"] == neg["id"] for i in negatives)
