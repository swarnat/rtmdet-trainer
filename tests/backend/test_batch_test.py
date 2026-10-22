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


def _label_image_3(session_factory, split: str = "validation") -> None:
    from odcore.db import Annotation

    with session_factory() as s:
        image = s.get(Image, 3)
        image.dataset_split = split
        image.annotations = [
            # matched by the person detection (500, 200, 700, 800)
            Annotation(class_name="person", x1=510, y1=210, x2=700, y2=800, type="positive", source="manual"),
            # missed: no detection here; the vehicle detection elsewhere is a false positive
            Annotation(class_name="vehicle", x1=100, y1=100, x2=300, y2=300, type="positive", source="manual"),
        ]
        s.commit()


def test_find_errors_matches_greedy_per_class():
    from app.services.batch_test import find_errors

    box = lambda x1, y1, x2, y2: {"x1": x1, "y1": y1, "x2": x2, "y2": y2}  # noqa: E731
    dets = [
        {"class": "person", "confidence": 0.9, "bbox": box(0, 0, 100, 100)},
        {"class": "person", "confidence": 0.8, "bbox": box(5, 5, 100, 100)},     # duplicate: FP
        {"class": "vehicle", "confidence": 0.7, "bbox": box(200, 200, 300, 300)},  # wrong class at a person: FP
    ]
    gts = [{"class": "person", "bbox": box(0, 0, 100, 100)}, {"class": "person", "bbox": box(200, 200, 300, 300)}]
    tp, fps, fns = find_errors(dets, gts)
    assert tp == 1
    assert [(d["class"], d["confidence"]) for d in fps] == [("person", 0.8), ("vehicle", 0.7)]
    assert fns == [{"class": "person", "bbox": box(200, 200, 300, 300)}]


def test_error_analysis_marks_images_with_fp_or_fn(env):
    client, session_factory = env
    _label_image_3(session_factory)
    res = client.post("/api/v1/batch-tests", json={"scope": "errors_validation"})
    assert res.status_code == 202
    batch = client.get(f"/api/v1/batch-tests/{res.json()['id']}").json()
    # default confidence of an error analysis = eval_confidence (as in the training evaluation)
    assert (batch["status"], batch["total"], batch["confidence"]) == ("completed", 1, 0.25)
    assert (batch["detections"], batch["marked_images"]) == (2, 1)

    listed = client.get("/api/v1/images", params={"has_errors": "true"}).json()["items"]
    assert [(i["id"], i["error_fp"], i["error_fn"]) for i in listed] == [(3, 1, 1)]
    mark = client.get("/api/v1/images/3").json()["error_mark"]
    assert mark["model_version"] == "model-0001" and mark["true_positives"] == 1
    assert [d["class"] for d in mark["false_positives"]] == ["vehicle"]
    assert mark["false_negatives"] == [{"class": "vehicle", "bbox": {"x1": 100.0, "y1": 100.0, "x2": 300.0, "y2": 300.0}}]
    assert client.get("/api/v1/images/2/neighbours", params={"has_errors": "true"}).json() == {"previous": None, "next": 3}
    # suggestions are not touched by an error analysis
    with session_factory() as s:
        assert s.query(ImageSuggestion).count() == 0

    # the mark can be dismissed (model wrong, annotations right) ...
    assert client.delete("/api/v1/images/3/error-mark").json()["error_mark"] is None
    # ... and is removed when the image is saved as labeled
    client.post("/api/v1/batch-tests", json={"scope": "errors_labeled"})
    assert client.get("/api/v1/images/3").json()["error_fp"] == 1
    client.put("/api/v1/images/3/annotations", json={"annotations": []})
    assert client.get("/api/v1/images", params={"has_errors": "true"}).json()["total"] == 0


def test_error_analysis_scope_and_replacement(env):
    client, session_factory = env
    _label_image_3(session_factory, split="train")
    # no labeled validation images
    assert client.post("/api/v1/batch-tests", json={"scope": "errors_validation"}).status_code == 409
    client.post("/api/v1/batch-tests", json={"scope": "errors_labeled"})
    assert client.get("/api/v1/images/3").json()["error_fn"] == 1
    # a new analysis replaces all previous marks; at a high threshold nothing is detected -> both boxes missed
    client.post("/api/v1/batch-tests", json={"scope": "errors_labeled", "confidence": 0.99})
    detail = client.get("/api/v1/images/3").json()
    assert (detail["error_fp"], detail["error_fn"], detail["error_mark"]["confidence"]) == (0, 2, 0.99)


def test_error_analysis_ignores_classes_not_reviewed(env):
    client, session_factory = env
    _label_image_3(session_factory)
    with session_factory() as s:
        s.get(Image, 3).reviewed_classes = ["person"]  # never checked for vehicles
        s.commit()
    batch = client.post("/api/v1/batch-tests", json={"scope": "errors_validation"}).json()
    assert client.get(f"/api/v1/batch-tests/{batch['id']}").json()["marked_images"] == 0


def test_filter_open_without_suggestions(env):
    client, session_factory = env
    with session_factory() as s:
        # image 1: suggestions with detections, image 2: batch test found nothing; image 3 is labeled
        s.add(ImageSuggestion(image_id=1, model_version="model-0001", input_width=1536, input_height=864, confidence=0.25,
                              detections_json=[{"class": "person", "confidence": 0.5, "bbox": {"x1": 1, "y1": 1, "x2": 9, "y2": 9}}]))
        s.add(ImageSuggestion(image_id=2, model_version="model-0001", input_width=1536, input_height=864, confidence=0.25,
                              detections_json=[]))
        s.add(Image(s3_object_key="images/9.jpg", sha256=f"{9:064d}", content_type="image/jpeg", size_bytes=1,
                    width=1920, height=1080, annotation_status="unlabeled"))  # no batch test yet
        s.commit()
    params = {"status": "unlabeled", "no_suggestions": "true"}
    assert [i["id"] for i in client.get("/api/v1/images", params=params).json()["items"]] == [2, 4]
    assert client.get("/api/v1/images/2/neighbours", params=params).json() == {"previous": None, "next": 4}


def test_filter_by_suggestion_confidence_level(env):
    client, session_factory = env
    det = lambda c: {"class": "person", "confidence": c, "bbox": {"x1": 1, "y1": 1, "x2": 9, "y2": 9}}  # noqa: E731
    with session_factory() as s:
        for i in range(4, 8):
            s.add(Image(s3_object_key=f"images/{i}.jpg", sha256=f"{i:064d}", content_type="image/jpeg", size_bytes=1,
                        width=1920, height=1080, annotation_status="unlabeled"))
        s.flush()
        # the weakest suggestion decides the level
        for image_id, confs in ((1, [0.9, 0.75]), (2, [0.95, 0.5]), (4, [0.4]), (5, [0.9, 0.3]), (6, [])):
            s.add(ImageSuggestion(image_id=image_id, model_version="model-0001", input_width=1536, input_height=864,
                                  confidence=0.25, detections_json=[det(c) for c in confs]))
        s.commit()
    ids = lambda level: [i["id"] for i in client.get("/api/v1/images", params={"suggestion_level": level}).json()["items"]]  # noqa: E731
    assert (ids("high"), ids("medium"), ids("low")) == ([1], [2, 4], [5])
    assert client.get("/api/v1/images/2/neighbours", params={"suggestion_level": "medium"}).json() == {"previous": None, "next": 4}


def test_scope_open_images_of_last_upload(env):
    from datetime import datetime, timedelta, timezone

    client, session_factory = env
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with session_factory() as s:
        for image in s.query(Image).all():  # images 1-3: an old upload
            image.created_at = old
        for i in (4, 5):  # new upload: image 4 open, image 5 already labeled
            s.add(Image(s3_object_key=f"images/{i}.jpg", sha256=f"{i:064d}", content_type="image/jpeg", size_bytes=1,
                        width=1920, height=1080, annotation_status="unlabeled" if i == 4 else "labeled",
                        created_at=old + timedelta(days=30, minutes=i)))
        s.commit()
    batch = client.post("/api/v1/batch-tests", json={"scope": "unlabeled_last_upload"}).json()
    assert client.get(f"/api/v1/batch-tests/{batch['id']}").json()["total"] == 1
    with session_factory() as s:
        assert [r.image_id for r in s.query(ImageSuggestion)] == [4]


def test_scope_untested_open_images(env):
    client, session_factory = env
    with session_factory() as s:  # image 1 was tested before (nothing found), image 2 never
        s.add(ImageSuggestion(image_id=1, model_version="model-0001", input_width=1536, input_height=864,
                              confidence=0.25, detections_json=[]))
        s.commit()
    batch = client.post("/api/v1/batch-tests", json={"scope": "unlabeled_untested"}).json()
    assert client.get(f"/api/v1/batch-tests/{batch['id']}").json()["total"] == 1
    with session_factory() as s:
        assert {r.image_id: r.batch_id for r in s.query(ImageSuggestion)} == {1: None, 2: batch["id"]}
    # all open images tested now: nothing left in scope
    assert client.post("/api/v1/batch-tests", json={"scope": "unlabeled_untested"}).status_code == 409


def test_find_errors_skips_detections_in_ignore_regions():
    from app.services.batch_test import find_errors

    box = lambda x1, y1, x2, y2: {"x1": x1, "y1": y1, "x2": x2, "y2": y2}  # noqa: E731
    dets = [
        {"class": "person", "confidence": 0.9, "bbox": box(0, 0, 100, 100)},      # TP
        {"class": "person", "confidence": 0.8, "bbox": box(220, 220, 280, 290)},  # inside the region: no error
        {"class": "person", "confidence": 0.7, "bbox": box(400, 400, 500, 500)},  # elsewhere: FP
        {"class": "vehicle", "confidence": 0.6, "bbox": box(220, 220, 280, 290)}, # the region applies to every class
    ]
    gts = [{"class": "person", "bbox": box(0, 0, 100, 100)}]
    ignore = [{"class": "person", "bbox": box(200, 200, 300, 300)}]
    tp, fps, fns = find_errors(dets, gts, ignore=ignore)
    assert tp == 1 and fns == []
    assert [(d["class"], d["confidence"]) for d in fps] == [("person", 0.7)]
    assert len(find_errors(dets, gts)[1]) == 3  # without regions the detection in it is a false positive
