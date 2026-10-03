"""Deleting model versions: guards, database cleanup, S3 artifacts and the local model cache."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from odcore.db import BatchStatus, ModelStatus, ModelVersion, PredictionBatch, TrainingRun, TrainingStatus

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services.model_registry import get_registry

from conftest import make_local_registry


class RecordingStorage:
    class settings:  # noqa: N801 - mimics S3Settings attributes
        bucket_models = "models"

    def __init__(self):
        self.deleted_prefixes: list[tuple[str, str]] = []

    def delete_prefix(self, bucket: str, prefix: str) -> int:
        self.deleted_prefixes.append((bucket, prefix))
        return 4


def model(version: str, status: ModelStatus) -> ModelVersion:
    return ModelVersion(version=version, status=status, checkpoint_key="base/rtmdet_s.pth", onnx_key=f"{version}/model.onnx",
                        openvino_key=f"{version}/openvino/model.xml", input_width=1536, input_height=864,
                        class_names=["person"])


@pytest.fixture()
def storage():
    return RecordingStorage()


@pytest.fixture()
def registry(tmp_path, constant_model_xml):
    return make_local_registry(constant_model_xml, str(tmp_path / "cache"))


@pytest.fixture()
def client(session_factory, storage, registry):
    with session_factory() as s:
        s.add_all([model("model-0001", ModelStatus.production), model("model-0002", ModelStatus.candidate)])
        s.commit()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_registry] = lambda: registry
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_run(session_factory, **kwargs) -> int:
    with session_factory() as s:
        run = TrainingRun(input_width=1536, input_height=864, epochs=1, batch_size=1, **kwargs)
        s.add(run)
        s.commit()
        return run.id


def test_delete_candidate_removes_row_artifacts_and_cache(client, session_factory, storage, registry):
    with session_factory() as s:
        mv_id = s.query(ModelVersion).filter_by(version="model-0002").one().id
    run_id = add_run(session_factory, base_model_id="rtmdet-s-coco", status=TrainingStatus.completed, model_version_id=mv_id)
    cached = os.path.join(registry.cache_dir, "model-0002")
    os.makedirs(cached)

    res = client.delete("/api/v1/models/model-0002")

    assert res.status_code == 204
    assert [m["version"] for m in client.get("/api/v1/models").json()] == ["model-0001"]
    # only the version's own folder; a shared COCO base checkpoint stays
    assert storage.deleted_prefixes == [("models", "model-0002/")]
    assert not os.path.exists(cached)
    with session_factory() as s:
        assert s.get(TrainingRun, run_id).model_version_id is None  # run history is kept


def test_production_model_cannot_be_deleted(client, storage):
    res = client.delete("/api/v1/models/model-0001")
    assert res.status_code == 409
    assert storage.deleted_prefixes == []


def test_model_used_by_running_training_cannot_be_deleted(client, session_factory, storage):
    add_run(session_factory, base_model_id="model-0002", status=TrainingStatus.running)
    assert client.delete("/api/v1/models/model-0002").status_code == 409
    assert storage.deleted_prefixes == []


def test_model_used_by_running_batch_test_cannot_be_deleted(client, session_factory):
    with session_factory() as s:
        s.add(PredictionBatch(status=BatchStatus.running, model_ref="candidate", model_version="model-0002",
                              input_width=1536, input_height=864, confidence=0.25))
        s.commit()
    assert client.delete("/api/v1/models/model-0002").status_code == 409


def test_delete_unknown_model(client):
    assert client.delete("/api/v1/models/model-0099").status_code == 404
