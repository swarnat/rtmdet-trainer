"""Training/model management endpoints (without queue/trainer)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from odcore.db import ModelStatus, ModelVersion, TrainingRun, TrainingStatus

from app.core.database import get_db
from app.main import app


@pytest.fixture()
def client(session_factory):
    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_version(s, version: str, status: ModelStatus) -> ModelVersion:
    mv = ModelVersion(version=version, status=status, checkpoint_key="c", onnx_key="o", openvino_key=f"{version}/openvino/model.xml",
                      input_width=1536, input_height=864, class_names=["person", "bicycle", "vehicle"])
    s.add(mv)
    s.commit()
    return mv


def test_training_run_serialises_model_version_string(client, session_factory):
    with session_factory() as s:
        mv = add_version(s, "model-0002", ModelStatus.candidate)
        s.add(TrainingRun(status=TrainingStatus.completed, base_model_id="rtmdet-s-coco", input_width=1536, input_height=864,
                          epochs=30, batch_size=4, model_version_id=mv.id, log="line\n"))
        s.commit()
    runs = client.get("/api/v1/training/runs").json()
    assert runs[0]["model_version"] == "model-0002"
    assert runs[0]["status"] == "completed"
    assert client.get(f"/api/v1/training/runs/{runs[0]['id']}/log").json()["log"] == "line\n"


def test_activate_and_rollback(client, session_factory):
    with session_factory() as s:
        add_version(s, "model-0001", ModelStatus.production)
        add_version(s, "model-0002", ModelStatus.candidate)
    assert client.post("/api/v1/models/model-0002/activate").json()["status"] == "production"
    status = {m["version"]: m["status"] for m in client.get("/api/v1/models").json()}
    assert status == {"model-0001": "archived", "model-0002": "production"}
    # rollback
    client.post("/api/v1/models/model-0001/activate")
    status = {m["version"]: m["status"] for m in client.get("/api/v1/models").json()}
    assert status == {"model-0001": "production", "model-0002": "archived"}
    assert client.post("/api/v1/models/model-0001/archive").status_code == 409


def test_training_requires_validation_images(client):
    res = client.post("/api/v1/training/runs", json={"input_size": "1536x864"})
    assert res.status_code == 409


def test_settings_validation(client):
    assert client.put("/api/v1/settings", json={"values": {"default_input_size": "1000x500"}}).status_code == 422
    res = client.put("/api/v1/settings", json={"values": {"default_confidence": 0.4}})
    assert res.status_code == 200 and res.json()["values"]["default_confidence"] == 0.4
