"""Hard negative annotations in the API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from odcore.db import Image

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


def add_image(session_factory, sha: str) -> int:
    with session_factory() as s:
        img = Image(s3_object_key=f"images/{sha}.jpg", sha256=sha, content_type="image/jpeg", size_bytes=1, width=1920, height=1080)
        s.add(img)
        s.commit()
        return img.id


HN = {"class": "person", "x1": 100, "y1": 80, "x2": 140, "y2": 150, "type": "hard_negative", "source": "prediction",
      "source_confidence": 0.4, "source_model": "model-0003"}


def test_hard_negative_roundtrip_and_counts(client, session_factory):
    image_id = add_image(session_factory, "a" * 64)
    detail = client.put(f"/api/v1/images/{image_id}/annotations", json={"annotations": [
        HN, {"class": "vehicle", "x1": 500, "y1": 500, "x2": 700, "y2": 650},
    ]}).json()
    hn = [a for a in detail["annotations"] if a["type"] == "hard_negative"][0]
    assert (hn["class"], hn["source_confidence"], hn["source_model"]) == ("person", 0.4, "model-0003")
    assert detail["annotation_count"] == 1 and detail["hard_negative_count"] == 1
    stats = client.get("/api/v1/images/stats").json()
    assert stats["annotations_per_class"]["person"] == 0
    assert stats["hard_negatives_per_class"]["person"] == 1
    elig = client.get("/api/v1/training/eligibility", params={"classes": "person,vehicle"}).json()
    assert elig["hard_negatives"] == 1
    classes = {c["name"]: c for c in client.get("/api/v1/classes").json()}
    assert classes["person"]["hard_negative_count"] == 1 and classes["person"]["annotation_count"] == 0
    # class with only hard negatives cannot be deleted either
    assert client.delete("/api/v1/classes/person").status_code == 409


def test_image_with_only_hard_negatives_is_negative(client, session_factory):
    image_id = add_image(session_factory, "b" * 64)
    detail = client.put(f"/api/v1/images/{image_id}/annotations", json={"annotations": [HN]}).json()
    assert detail["annotation_count"] == 0
    assert client.get("/api/v1/images/stats").json()["images_negative"] == 1
    items = client.get("/api/v1/images", params={"negative": "true"}).json()["items"]
    assert [(i["id"], i["hard_negative_count"]) for i in items] == [(image_id, 1)]


def test_positive_boxes_drop_source_metadata(client, session_factory):
    image_id = add_image(session_factory, "c" * 64)
    body = {**HN, "type": "positive"}
    a = client.put(f"/api/v1/images/{image_id}/annotations", json={"annotations": [body]}).json()["annotations"][0]
    assert a["type"] == "positive" and a["source_confidence"] is None and a["source_model"] is None


def test_hard_negative_settings_validation(client):
    assert client.put("/api/v1/settings", json={"values": {"hard_negative_oversample": 50}}).status_code == 422
    res = client.put("/api/v1/settings", json={"values": {"hard_negative_context_factor": 2.5}})
    assert res.json()["values"]["hard_negative_context_factor"] == 2.5
