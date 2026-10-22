"""System reset: deletes images, training runs and custom models, restores the default classes, keeps settings."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from odcore.classes import DEFAULT_CLASSES
from odcore.db import (Annotation, AnnotationStatus, BatchStatus, Candidate, CandidateSearch, DeletedImage, DetectionClass, Image, ImageSuggestion,
                       ModelStatus, ModelVersion, PredictionBatch, SnapshotImage, TrainingRun, TrainingStatus)
from odcore.settings_store import get_setting, set_setting

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services.model_registry import get_registry


class RecordingStorage:
    class settings:  # noqa: N801 - mimics S3Settings attributes
        bucket_images = "training-images"
        bucket_datasets = "datasets"
        bucket_models = "models"

    def __init__(self):
        self.deleted_prefixes: list[tuple[str, str]] = []

    def delete_prefix(self, bucket: str, prefix: str) -> int:
        self.deleted_prefixes.append((bucket, prefix))
        return 0


class RecordingRegistry:
    def __init__(self):
        self.forgotten: list[str] = []

    def forget(self, version: str) -> None:
        self.forgotten.append(version)


def model(version: str, kind: str, classes: list[str], status: ModelStatus = ModelStatus.archived) -> ModelVersion:
    return ModelVersion(version=version, kind=kind, status=status, architecture="rtmdet-s", checkpoint_key="x", onnx_key="x",
                        openvino_key=f"{version}/openvino/model.xml", input_width=1536, input_height=864, class_names=classes)


def image(n: int, **kw) -> Image:
    return Image(s3_object_key=f"images/{n}.jpg", sha256=f"{n:064d}", content_type="image/jpeg", size_bytes=1, width=160,
                 height=120, **kw)


@pytest.fixture()
def env(session_factory, monkeypatch, tmp_path):
    queued: list[tuple] = []
    monkeypatch.setattr("app.core.queue.enqueue_bootstrap", lambda force, base: queued.append((force, base)) or "job-1")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "no-backups"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    storage, registry = RecordingStorage(), RecordingRegistry()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_registry] = lambda: registry
    yield TestClient(app), session_factory, storage, registry, queued
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def populate(session_factory, bootstrap: bool = True) -> None:
    with session_factory() as s:
        s.add(DetectionClass(name="dog", label="Hund", color="#123456", coco_classes=["dog"], sort_order=9, active=True))
        s.get(DetectionClass, 1).label = "Mensch"  # renamed default class
        first = image(1, annotation_status=AnnotationStatus.labeled)
        first.annotations.append(Annotation(class_name="person", x1=1, y1=1, x2=9, y2=9))
        s.add_all([first, image(2)])
        s.add(DeletedImage(sha256="f" * 64))
        s.flush()
        s.add(ImageSuggestion(image_id=2, model_version="model-0003", input_width=1536, input_height=864, confidence=0.3,
                              detections_json=[]))
        run = TrainingRun(status=TrainingStatus.completed, base_model_id="rtmdet-s-coco", input_width=1536, input_height=864,
                          epochs=1, batch_size=1, dataset_snapshot="1/")
        s.add(run)
        s.flush()
        s.add(SnapshotImage(training_run_id=run.id, image_id=1))
        if bootstrap:
            s.add(model("model-0001", "coco-bootstrap", ["person", "vehicle"]))
            s.add(model("model-0002", "coco-bootstrap", ["person", "dog"]))  # custom class: not kept
        trained = model("model-0003", "trained", ["person", "bicycle", "vehicle"], ModelStatus.production)
        trained.training_run_id = run.id
        s.add(trained)
        s.add(PredictionBatch(status=BatchStatus.completed, model_ref="production", input_width=1536, input_height=864,
                              confidence=0.3))
        search = CandidateSearch(class_name="dog", prompts=["dog"], status=BatchStatus.completed)
        s.add(search)
        s.flush()
        s.add(Candidate(search_id=search.id, image_id=2, x1=1, y1=1, x2=50, y2=50, score=0.5))
        set_setting(s, "deployment_url", "http://prod:8100")
        s.commit()


def test_preview(env):
    client, session_factory, *_ = env
    populate(session_factory)
    body = client.get("/api/v1/system/reset").json()
    assert (body["images"], body["annotations"], body["training_runs"]) == (2, 1, 1)
    assert body["models_deleted"] == ["model-0002", "model-0003"] and body["models_kept"] == ["model-0001"]
    assert body["classes"] == ["person", "bicycle", "vehicle"] and body["blocked_by"] == []


@pytest.mark.parametrize("confirm", ["", "yes", "RESE"])
def test_reset_needs_confirmation(env, confirm):
    client, session_factory, storage, *_ = env
    populate(session_factory)
    assert client.post("/api/v1/system/reset", json={"confirm": confirm}).status_code == 422
    with session_factory() as s:
        assert s.query(Image).count() == 2
    assert storage.deleted_prefixes == []


def test_reset_deletes_everything_but_settings_and_bootstrap(env):
    client, session_factory, storage, registry, queued = env
    populate(session_factory)
    res = client.post("/api/v1/system/reset", json={"confirm": " Reset "})
    assert res.status_code == 200
    body = res.json()
    assert body["production_model"] == "model-0001" and body["bootstrap_queued"] is False and body["warnings"] == []
    with session_factory() as s:
        for table in (Image, Annotation, ImageSuggestion, DeletedImage, SnapshotImage, TrainingRun, PredictionBatch, CandidateSearch, Candidate):
            assert s.query(table).count() == 0, table.__name__
        assert [(m.version, m.status) for m in s.query(ModelVersion)] == [("model-0001", ModelStatus.production)]
        classes = s.query(DetectionClass).order_by(DetectionClass.sort_order).all()
        assert [(c.name, c.label, c.color) for c in classes] == [(c["name"], c["label"], c["color"]) for c in DEFAULT_CLASSES]
        assert get_setting(s, "deployment_url") == "http://prod:8100"
    assert storage.deleted_prefixes == [("training-images", ""), ("datasets", ""), ("models", "model-0002/"),
                                        ("models", "model-0003/")]
    assert registry.forgotten == ["model-0002", "model-0003"] and queued == []


def test_reset_without_bootstrap_model_queues_import(env):
    client, session_factory, _, _, queued = env
    populate(session_factory, bootstrap=False)
    body = client.post("/api/v1/system/reset", json={"confirm": "reset"}).json()
    assert body["production_model"] is None and body["bootstrap_queued"] is True
    assert queued == [(False, "rtmdet-s-coco")]
    with session_factory() as s:
        assert s.query(ModelVersion).count() == 0


@pytest.mark.parametrize("job", ["training", "batch", "candidates"])
def test_reset_refused_while_jobs_run(env, job):
    client, session_factory, storage, *_ = env
    populate(session_factory)
    with session_factory() as s:
        if job == "training":
            s.add(TrainingRun(status=TrainingStatus.running, base_model_id="rtmdet-s-coco", input_width=1536,
                              input_height=864, epochs=1, batch_size=1))
        elif job == "candidates":
            s.add(CandidateSearch(class_name="dog", prompts=["dog"], status=BatchStatus.running))
        else:
            s.add(PredictionBatch(status=BatchStatus.queued, model_ref="production", input_width=1536, input_height=864,
                                  confidence=0.3))
        s.commit()
    assert client.get("/api/v1/system/reset").json()["blocked_by"]
    res = client.post("/api/v1/system/reset", json={"confirm": "reset"})
    assert res.status_code == 409 and "not possible" in res.json()["detail"]
    with session_factory() as s:
        assert s.query(Image).count() == 2
    assert storage.deleted_prefixes == []
