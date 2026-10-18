"""Client annotator: settings, configuration push, import of annotated/checked images, clearing the client."""
from __future__ import annotations

import json
import re

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import AnnotationStatus, DeletedImage, Image, ImageSuggestion

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services import client_annotator

TOKEN = "client-token-0123456789"


def jpeg(seed: int) -> bytes:
    image = np.random.default_rng(seed).integers(0, 255, (120, 160, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


class MemoryStorage:
    class settings:  # noqa: N801 - mimics S3Settings attributes
        bucket_images = "training-images"

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data


def client_image(image_id: int, status: str = "open", annotations=None, detection=None) -> dict:
    return {"id": image_id, "sha256": "x", "filename": f"cam{image_id}.jpg", "source_url": None, "content_type": "image/jpeg",
            "size_bytes": 1, "width": 160, "height": 120, "status": status, "annotations": annotations or [],
            "detection": detection, "created_at": "2026-10-18T10:00:00+00:00", "updated_at": "2026-10-18T10:00:00+00:00",
            "annotated_at": None}


DETECTION = {"model_version": "model-0007", "input_width": 1536, "input_height": 864, "confidence": 0.3, "inference_ms": 10,
             "detections": [{"class": "person", "confidence": 0.9, "bbox": {"x1": 10, "y1": 20, "x2": 50, "y2": 100}}],
             "created_at": "2026-10-18T10:00:00+00:00"}


class FakeClient:
    """In-memory client annotator API: records requests."""

    def __init__(self):
        self.images: dict[int, dict] = {}
        self.files: dict[int, bytes] = {}
        self.config = None
        self.requests: list[httpx.Request] = []
        self.fail_delete = False

    def add(self, image: dict, data: bytes) -> None:
        self.images[image["id"]] = image
        self.files[image["id"]] = data

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if request.headers.get("x-access-key") != TOKEN:
            return httpx.Response(401, json={"detail": "invalid or missing access token"})
        path, method = request.url.path, request.method
        if path == "/api/v1/config":
            if method == "PUT":
                self.config = {**json.loads(request.content), "pushed_at": "2026-10-18T10:00:00+00:00"}
            return httpx.Response(200, json=self.config)
        if path == "/api/v1/images":
            counts = {"total": len(self.images), "open": sum(i["status"] == "open" for i in self.images.values())}
            counts["annotated"] = counts["total"] - counts["open"]
            limit = request.url.params.get("limit")
            items = list(self.images.values())[: int(limit) if limit is not None else None]
            return httpx.Response(200, json={"counts": counts, "items": items})
        m = re.fullmatch(r"/api/v1/images/(\d+)(/file)?", path)
        if not m or int(m.group(1)) not in self.images:
            return httpx.Response(404, json={"detail": "not found"})
        image_id = int(m.group(1))
        if m.group(2):
            return httpx.Response(200, content=self.files[image_id])
        if method == "DELETE":
            if self.fail_delete:
                return httpx.Response(500, json={"detail": "disk full"})
            del self.images[image_id]
            return httpx.Response(204)
        return httpx.Response(200, json=self.images[image_id])


@pytest.fixture()
def env(session_factory, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(client_annotator, "http_client", lambda timeout: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    storage = MemoryStorage()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: storage
    yield TestClient(app), session_factory, fake
    app.dependency_overrides.clear()


def configure(client, **extra):
    values = {"client_annotator_url": "http://kunde.example.com:8200/", "client_annotator_access_key": TOKEN, **extra}
    res = client.put("/api/v1/settings", json={"values": values})
    assert res.status_code == 200
    return res.json()["values"]


def test_not_configured(env):
    client, _, _ = env
    assert client.get("/api/v1/client-annotator").json()["configured"] is False
    assert client.post("/api/v1/client-annotator/config").status_code == 409
    assert client.get("/api/v1/client-annotator/images").status_code == 409
    assert client.post("/api/v1/client-annotator/images/1/import").status_code == 409


def test_settings_mask_token_and_validate(env):
    client, _, _ = env
    values = configure(client)
    assert values["client_annotator_url"] == "http://kunde.example.com:8200"
    assert values["client_annotator_access_key"] == "********"
    assert client.put("/api/v1/settings", json={"values": {"client_annotator_access_key": "short"}}).status_code == 422
    assert client.put("/api/v1/settings", json={"values": {"client_inference_url": "ftp://x"}}).status_code == 422


def test_push_config_and_status(env):
    client, session_factory, fake = env
    configure(client, deployment_url="http://prod:8100")
    res = client.post("/api/v1/client-annotator/config")
    assert res.status_code == 200
    assert [c["name"] for c in fake.config["classes"]] == ["person", "bicycle", "vehicle"]
    assert fake.config["classes"][0] == {"name": "person", "label": "Person", "color": "#e53935"}
    assert fake.config["inference_url"] == "http://prod:8100"  # fallback: URL of the production system
    assert fake.config["confidence"] == 0.25
    assert str(fake.requests[-1].url) == "http://kunde.example.com:8200/api/v1/config"
    configure(client, client_inference_url="http://localhost:8100")
    client.post("/api/v1/client-annotator/config")
    assert fake.config["inference_url"] == "http://localhost:8100"

    fake.add(client_image(1, "annotated"), jpeg(1))
    st = client.get("/api/v1/client-annotator").json()
    assert st["reachable"] is True and st["counts"] == {"total": 1, "open": 0, "annotated": 1}
    assert st["config"]["inference_url"] == "http://localhost:8100"
    assert fake.requests[-1].url.params["limit"] == "0"  # counts only


def test_wrong_token_is_reported(env):
    client, _, _ = env
    configure(client, client_annotator_access_key="another-token-0123456789")
    st = client.get("/api/v1/client-annotator").json()
    assert st["reachable"] is False and "HTTP 401" in st["error"]
    assert client.post("/api/v1/client-annotator/config").status_code == 502


def test_list_images(env):
    client, _, fake = env
    configure(client)
    fake.add(client_image(1, "annotated", [{"class": "person", "x1": 1, "y1": 1, "x2": 9, "y2": 9}]), jpeg(1))
    fake.add(client_image(2, detection=DETECTION), jpeg(2))
    fake.add(client_image(3), jpeg(3))
    body = client.get("/api/v1/client-annotator/images").json()
    assert body["counts"]["total"] == 3
    assert [(i["id"], i["status"], i["annotations"], i["detections"]) for i in body["items"]] == [
        (1, "annotated", 1, None), (2, "open", 0, 1), (3, "open", 0, None)]


def test_import_annotated_image_is_labeled_and_removed_from_client(env):
    client, session_factory, fake = env
    configure(client)
    boxes = [
        {"class": "person", "x1": 10, "y1": 10, "x2": 60, "y2": 90, "type": "positive", "source": "prediction",
         "source_confidence": None, "source_model": None},
        {"class": "vehicle", "x1": 80, "y1": 10, "x2": 150, "y2": 60, "type": "hard_negative", "source": "prediction",
         "source_confidence": 0.4, "source_model": "model-0007"},
    ]
    fake.add(client_image(5, "annotated", boxes, DETECTION), jpeg(1))
    r = client.post("/api/v1/client-annotator/images/5/import").json()
    assert r["status"] == "created" and r["applied"] == "annotations" and r["client_deleted"] is True
    assert r["filename"] == "cam5.jpg"
    assert 5 not in fake.images
    with session_factory() as s:
        image = s.get(Image, r["image_id"])
        assert image.annotation_status == AnnotationStatus.labeled and image.dataset_split is not None
        assert [(a.class_name, a.type, a.source) for a in image.annotations] == [
            ("person", "positive", "prediction"), ("vehicle", "hard_negative", "prediction")]
        assert image.annotations[1].source_confidence == 0.4
        assert s.query(ImageSuggestion).count() == 0


def test_import_negative_image(env):
    client, session_factory, fake = env
    configure(client)
    fake.add(client_image(1, "annotated"), jpeg(1))
    r = client.post("/api/v1/client-annotator/images/1/import").json()
    assert r["applied"] == "annotations"
    with session_factory() as s:
        image = s.get(Image, r["image_id"])
        assert image.annotation_status == AnnotationStatus.labeled and image.annotations == []


def test_import_open_image_keeps_check_as_suggestions(env):
    client, session_factory, fake = env
    configure(client)
    fake.add(client_image(1, detection=DETECTION), jpeg(1))
    fake.add(client_image(2), jpeg(2))
    r1 = client.post("/api/v1/client-annotator/images/1/import").json()
    r2 = client.post("/api/v1/client-annotator/images/2/import").json()
    assert (r1["applied"], r2["applied"]) == ("suggestions", "none")
    assert fake.images == {}
    with session_factory() as s:
        assert s.get(Image, r1["image_id"]).annotation_status == AnnotationStatus.unlabeled
        suggestion = s.query(ImageSuggestion).one()
        assert suggestion.image_id == r1["image_id"] and suggestion.batch_id is None
        assert (suggestion.model_version, suggestion.input_width, suggestion.confidence) == ("model-0007", 1536, 0.3)
        assert suggestion.detections_json == DETECTION["detections"]


def test_import_duplicate_keeps_labeled_annotations(env):
    client, session_factory, fake = env
    configure(client)
    fake.add(client_image(1, "annotated", [{"class": "person", "x1": 1, "y1": 1, "x2": 9, "y2": 9, "type": "positive",
                                            "source": "manual", "source_confidence": None, "source_model": None}]), jpeg(1))
    first = client.post("/api/v1/client-annotator/images/1/import").json()
    # the same image again from the next batch, annotated differently
    fake.add(client_image(2, "annotated", []), jpeg(1))
    again = client.post("/api/v1/client-annotator/images/2/import").json()
    assert again["status"] == "duplicate" and again["applied"] == "kept" and again["image_id"] == first["image_id"]
    assert again["client_deleted"] is True
    with session_factory() as s:
        assert len(s.get(Image, first["image_id"]).annotations) == 1


def test_import_duplicate_of_open_image_applies_annotations(env):
    client, session_factory, fake = env
    configure(client)
    fake.add(client_image(1), jpeg(1))
    first = client.post("/api/v1/client-annotator/images/1/import").json()
    fake.add(client_image(2, "annotated", []), jpeg(1))
    again = client.post("/api/v1/client-annotator/images/2/import").json()
    assert again["status"] == "duplicate" and again["applied"] == "annotations"
    with session_factory() as s:
        assert s.get(Image, first["image_id"]).annotation_status == AnnotationStatus.labeled


def test_import_of_deleted_image_is_skipped_but_cleared(env):
    client, session_factory, fake = env
    configure(client)
    import hashlib

    with session_factory() as s:
        s.add(DeletedImage(sha256=hashlib.sha256(jpeg(1)).hexdigest()))
        s.commit()
    fake.add(client_image(1, "annotated"), jpeg(1))
    r = client.post("/api/v1/client-annotator/images/1/import").json()
    assert r["status"] == "deleted" and r["client_deleted"] is True
    with session_factory() as s:
        assert s.query(Image).count() == 0


def test_errors_keep_the_image_on_the_client(env):
    client, session_factory, fake = env
    configure(client)
    fake.add(client_image(1, "annotated", [{"class": "dog", "x1": 1, "y1": 1, "x2": 9, "y2": 9}]), jpeg(1))
    fake.add(client_image(2), b"no image")
    r1 = client.post("/api/v1/client-annotator/images/1/import").json()
    r2 = client.post("/api/v1/client-annotator/images/2/import").json()
    r3 = client.post("/api/v1/client-annotator/images/99/import").json()
    assert r1["status"] == "error" and "unknown class 'dog'" in r1["error"] and not r1["client_deleted"]
    assert r2["status"] == "error" and "unsupported image format" in r2["error"]
    assert r3["status"] == "error" and "HTTP 404" in r3["error"]
    assert set(fake.images) == {1, 2}


def test_failed_delete_on_client_is_reported(env):
    client, _, fake = env
    configure(client)
    fake.fail_delete = True
    fake.add(client_image(1), jpeg(1))
    r = client.post("/api/v1/client-annotator/images/1/import").json()
    assert r["status"] == "created" and r["client_deleted"] is False and "not deleted on the client" in r["error"]


@pytest.mark.parametrize("configured, expected", [("http://proxy.local:8888", "http://proxy.local:8888"), ("", None)])
def test_http_client_uses_deployment_proxy(monkeypatch, configured, expected):
    monkeypatch.setattr(client_annotator, "get_settings", lambda: type("S", (), {"deployment_proxy": configured})())
    monkeypatch.setattr(client_annotator.httpx, "Client", lambda **kw: kw)
    assert client_annotator.http_client(client_annotator.TIMEOUT)["proxy"] == expected
