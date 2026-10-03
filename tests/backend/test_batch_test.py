"""Batch test: suggestions for open images."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import BatchStatus, Image, ImageSuggestion, ModelStatus, ModelVersion, PredictionBatch

from app.api.routes import batch_tests as batch_routes
from app.core.database import get_db
from app.main import app
from app.services.batch_test import run_batch

from conftest import FakeStorage, make_local_registry


def jpeg() -> bytes:
    image = np.random.default_rng(3).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


@pytest.fixture()
def env(tmp_path, session_factory, constant_model_xml, monkeypatch):
    registry = make_local_registry(constant_model_xml, str(tmp_path / "cache"))
    storage = FakeStorage(jpeg())
    with session_factory() as s:
        s.add(ModelVersion(version="model-0001", status=ModelStatus.production, checkpoint_key="x", onnx_key="x",
                           openvino_key="model-0001/openvino/model.xml", input_width=1536, input_height=864,
                           class_names=["person", "bicycle", "vehicle"]))
        for i, status in enumerate(["unlabeled", "unlabeled", "labeled"]):
            s.add(Image(s3_object_key=f"images/{i}.jpg", sha256=f"{i:064d}", content_type="image/jpeg", size_bytes=1,
                        width=1920, height=1080, annotation_status=status,
                        reviewed_classes=["person", "bicycle", "vehicle"] if status == "labeled" else None))
        s.commit()

    class SyncRunner:
        def submit(self, batch_id: int) -> None:
            run_batch(batch_id, session_factory, storage, registry)

    monkeypatch.setattr(batch_routes, "get_runner", lambda: SyncRunner())

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    yield TestClient(app), session_factory
    app.dependency_overrides.clear()


def test_batch_creates_suggestions_for_open_images(env):
    client, session_factory = env
    res = client.post("/api/v1/batch-tests", json={})
    assert res.status_code == 202
    batch = client.get(f"/api/v1/batch-tests/{res.json()['id']}").json()
    assert batch["status"] == "completed" and batch["model_version"] == "model-0001"
    assert (batch["total"], batch["processed"], batch["detections"], batch["failed_images"]) == (2, 2, 4, 0)

    images = {i["id"]: i for i in client.get("/api/v1/images").json()["items"]}
    assert [images[i]["suggestion_count"] for i in (1, 2, 3)] == [2, 2, None]
    assert [i["id"] for i in client.get("/api/v1/images", params={"has_suggestions": "true"}).json()["items"]] == [1, 2]

    detail = client.get("/api/v1/images/1").json()
    sug = detail["suggestion"]
    assert sug["model_version"] == "model-0001" and sug["confidence"] == 0.25
    assert [(d["class"], d["bbox"]) for d in sug["detections"]] == [
        ("person", {"x1": 500, "y1": 200, "x2": 700, "y2": 800}),
        ("vehicle", {"x1": 1000, "y1": 500, "x2": 1250, "y2": 750}),
    ]

    # saving the image as labeled consumes its suggestions
    saved = client.put("/api/v1/images/1/annotations", json={"annotations": [
        {"class": "person", "x1": 500, "y1": 200, "x2": 700, "y2": 800, "source": "prediction"}]}).json()
    assert saved["suggestion"] is None
    with session_factory() as s:
        assert s.query(ImageSuggestion).count() == 1


def test_rerun_replaces_suggestions_and_scope(env):
    client, session_factory = env
    client.post("/api/v1/batch-tests", json={"confidence": 0.7})
    client.post("/api/v1/batch-tests", json={"confidence": 0.05, "scope": "unlabeled_and_review"})
    with session_factory() as s:
        rows = s.query(ImageSuggestion).order_by(ImageSuggestion.image_id).all()
        # rerun replaced the 0.7 suggestions; labeled image is fully reviewed, so not in scope
        assert [(r.image_id, r.confidence, len(r.detections_json)) for r in rows] == [(1, 0.05, 3), (2, 0.05, 3)]


def test_validation_and_cancel(env):
    client, session_factory = env
    assert client.post("/api/v1/batch-tests", json={"model": "model-0099"}).status_code == 404
    assert client.post("/api/v1/batch-tests", json={"input_size": "1000x500"}).status_code == 422
    with session_factory() as s:
        s.add(PredictionBatch(status=BatchStatus.running, model_ref="production", input_width=1536, input_height=864,
                              confidence=0.25, scope="unlabeled"))
        s.commit()
    assert client.post("/api/v1/batch-tests", json={}).status_code == 409  # one batch at a time
    assert client.post("/api/v1/batch-tests/1/cancel").json()["status"] == "cancelled"
    assert client.post("/api/v1/batch-tests/1/cancel").status_code == 409
