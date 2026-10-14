"""API detection tests with a real OpenVINO model and the full request path."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import ModelStatus, ModelVersion

from app.core.database import get_db
from app.main import app
from app.services.model_registry import get_registry

from conftest import make_local_registry


@pytest.fixture()
def client(tmp_path, session_factory, constant_model_xml):
    registry = make_local_registry(constant_model_xml, str(tmp_path / "cache"))
    with session_factory() as s:
        s.add(ModelVersion(version="model-0001", status=ModelStatus.archived, checkpoint_key="x", onnx_key="x",
                           openvino_key="model-0001/openvino/model.xml", input_width=1536, input_height=864,
                           class_names=["person", "bicycle", "vehicle"]))
        s.add(ModelVersion(version="model-0002", status=ModelStatus.production, checkpoint_key="x", onnx_key="x",
                           openvino_key="model-0002/openvino/model.xml", input_width=1536, input_height=864,
                           class_names=["person", "bicycle", "vehicle"]))
        s.commit()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_registry] = lambda: registry
    yield TestClient(app)
    app.dependency_overrides.clear()


def jpeg(width: int, height: int) -> bytes:
    image = np.random.default_rng(1).integers(0, 255, (height, width, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return buf.tobytes()


def test_detect_returns_boxes_in_original_coordinates(client):
    res = client.post("/api/v1/detect", files={"image": ("cam.jpg", jpeg(1920, 1080), "image/jpeg")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["image"] == {"width": 1920, "height": 1080}
    assert body["model"] == {"version": "model-0002", "status": "production", "input_width": 1536, "input_height": 864}
    assert body["inference_ms"] > 0
    dets = body["detections"]
    # duplicate removed by NMS, low-confidence bicycle filtered by default threshold 0.25
    assert [d["class"] for d in dets] == ["person", "vehicle"]
    assert dets[0]["confidence"] == pytest.approx(0.9, abs=1e-3)
    assert dets[0]["bbox"] == {"x1": 500, "y1": 200, "x2": 700, "y2": 800}
    assert dets[1]["bbox"] == {"x1": 1000, "y1": 500, "x2": 1250, "y2": 750}


def test_detect_with_explicit_model_size_and_confidence(client):
    res = client.post(
        "/api/v1/detect",
        files={"image": ("cam.png", jpeg(1920, 1080), "image/jpeg")},
        data={"model": "model-0001", "input_size": "1024x576", "confidence": "0.05"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["model"]["version"] == "model-0001"
    assert (body["model"]["input_width"], body["model"]["input_height"]) == (1024, 576)
    # raw boxes are now interpreted in 1024x576 input pixels -> scale 1920/1024 = 1.875
    assert [d["class"] for d in body["detections"]] == ["person", "vehicle", "bicycle"]
    assert body["detections"][0]["bbox"] == {"x1": 750, "y1": 300, "x2": 1050, "y2": 1080}


def test_detect_rejects_invalid_input_size(client):
    res = client.post("/api/v1/detect", files={"image": ("a.jpg", jpeg(64, 36), "image/jpeg")}, data={"input_size": "1000x500"})
    assert res.status_code == 422
    assert "multiple of 32" in res.json()["detail"]


def test_detect_rejects_non_image(client):
    res = client.post("/api/v1/detect", files={"image": ("a.txt", b"hello", "text/plain")})
    assert res.status_code == 422


def test_detect_unknown_model_version(client):
    res = client.post("/api/v1/detect", files={"image": ("a.jpg", jpeg(64, 36), "image/jpeg")}, data={"model": "model-0099"})
    assert res.status_code == 404


def test_detect_without_production_model(client, session_factory):
    with session_factory() as s:
        s.query(ModelVersion).update({ModelVersion.status: ModelStatus.archived})
        s.commit()
    res = client.post("/api/v1/detect", files={"image": ("a.jpg", jpeg(64, 36), "image/jpeg")})
    assert res.status_code == 503


def test_compiled_models_are_cached_per_resolution(client):
    for size in ("1536x864", "1536x864", "768x448"):
        client.post("/api/v1/detect", files={"image": ("a.jpg", jpeg(320, 180), "image/jpeg")}, data={"input_size": size})
    loaded = client.get("/api/v1/models/loaded").json()
    assert sorted((m["input_width"], m["input_height"]) for m in loaded) == [(768, 448), (1536, 864)]


def test_detect_url_downloads_and_returns_image(client, monkeypatch):
    import app.api.routes.detect as detect_route

    data = jpeg(1920, 1080)
    monkeypatch.setattr(detect_route, "download_image", lambda url: data)
    res = client.post("/api/v1/detect/url", json={"url": "http://cam/a.jpg", "confidence": 0.5})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [d["class"] for d in body["detections"]] == ["person", "vehicle"]
    assert body["image_data_url"].startswith("data:image/jpeg;base64,")


def test_detect_url_reports_download_errors(client, monkeypatch):
    import app.api.routes.detect as detect_route
    from app.services.url_download import DownloadError

    def fail(url):
        raise DownloadError("HTTP 404")

    monkeypatch.setattr(detect_route, "download_image", fail)
    res = client.post("/api/v1/detect/url", json={"url": "http://cam/missing.jpg"})
    assert res.status_code == 422 and "HTTP 404" in res.json()["detail"]
    monkeypatch.setattr(detect_route, "download_image", lambda url: b"<html>no image</html>")
    assert client.post("/api/v1/detect/url", json={"url": "http://cam/page"}).status_code == 422
