"""Configurable classes: management API, review tracking and training eligibility."""
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


def add_image(session_factory, sha: str, split: str | None = None) -> int:
    with session_factory() as s:
        img = Image(s3_object_key=f"images/{sha}.jpg", sha256=sha, content_type="image/jpeg", size_bytes=1, width=1920, height=1080)
        s.add(img)
        s.commit()
        return img.id


def save(client, image_id: int, boxes: list[dict]):
    return client.put(f"/api/v1/images/{image_id}/annotations", json={"annotations": boxes})


def box(cls: str) -> dict:
    return {"class": cls, "x1": 10, "y1": 10, "x2": 100, "y2": 100}


def test_initial_classes(client):
    res = client.get("/api/v1/classes").json()
    assert [c["name"] for c in res] == ["person", "bicycle", "vehicle"]
    assert res[2]["coco_classes"] == ["car", "motorcycle", "bus", "truck"]
    assert "train" in client.get("/api/v1/classes/coco").json()


def test_create_class_validation(client):
    ok = client.post("/api/v1/classes", json={"name": "battery", "label": "Batterie"})
    assert ok.status_code == 201
    body = ok.json()
    assert body["coco_classes"] == [] and body["color"].startswith("#") and body["sort_order"] == 3
    assert client.post("/api/v1/classes", json={"name": "battery", "label": "x"}).status_code == 409
    assert client.post("/api/v1/classes", json={"name": "Battery!", "label": "x"}).status_code == 422
    assert client.post("/api/v1/classes", json={"name": "ladder", "label": "x", "coco_classes": ["ladder"]}).status_code == 422
    res = client.post("/api/v1/classes", json={"name": "truck_only", "label": "LKW", "coco_classes": ["truck"]})
    assert res.json()["coco_classes"] == ["truck"]


def test_update_reorder_delete(client, session_factory):
    assert client.patch("/api/v1/classes/vehicle", json={"label": "Kfz", "coco_classes": ["car"]}).json()["label"] == "Kfz"
    order = client.put("/api/v1/classes/order", json={"names": ["vehicle", "person", "bicycle"]}).json()
    assert [c["name"] for c in order] == ["vehicle", "person", "bicycle"]
    assert client.put("/api/v1/classes/order", json={"names": ["vehicle"]}).status_code == 422
    # delete only without annotations
    image_id = add_image(session_factory, "a" * 64)
    assert save(client, image_id, [box("bicycle")]).status_code == 200
    assert client.delete("/api/v1/classes/bicycle").status_code == 409
    assert client.patch("/api/v1/classes/bicycle", json={"active": False}).json()["active"] is False
    assert client.delete("/api/v1/classes/person").status_code == 204
    # the last active class cannot be deactivated
    assert client.patch("/api/v1/classes/vehicle", json={"active": False}).status_code == 409


def test_unknown_class_rejected(client, session_factory):
    image_id = add_image(session_factory, "b" * 64)
    res = save(client, image_id, [box("battery")])
    assert res.status_code == 422 and "unknown class" in res.json()["detail"]


def test_new_class_requires_review(client, session_factory):
    image_id = add_image(session_factory, "c" * 64)
    detail = save(client, image_id, [box("person")]).json()
    assert detail["reviewed_classes"] == ["person", "bicycle", "vehicle"] and detail["needs_review"] is False

    client.post("/api/v1/classes", json={"name": "battery", "label": "Batterie"})
    detail = client.get(f"/api/v1/images/{image_id}").json()
    assert detail["needs_review"] is True
    listed = client.get("/api/v1/images", params={"needs_review": "true"}).json()
    assert [i["id"] for i in listed["items"]] == [image_id]
    assert client.get("/api/v1/images/stats").json()["images_needs_review"] == 1

    # old classes stay usable, the new class is not
    old = client.get("/api/v1/training/eligibility", params={"classes": "person,vehicle"}).json()
    assert old["needs_review"] == 0 and sum(old["usable"].values()) == 1
    new = client.get("/api/v1/training/eligibility", params={"classes": "battery"}).json()
    assert new["needs_review"] == 1 and sum(new["usable"].values()) == 0

    # re-check and save -> reviewed for battery as well; image without battery = negative for it
    detail = save(client, image_id, [box("person")]).json()
    assert detail["needs_review"] is False
    new = client.get("/api/v1/training/eligibility", params={"classes": "battery"}).json()
    assert sum(new["usable"].values()) == 1 and new["negative"] == 1


def test_training_rejects_inactive_or_unknown_classes(client):
    client.post("/api/v1/classes", json={"name": "battery", "label": "Batterie"})
    client.patch("/api/v1/classes/battery", json={"active": False})
    res = client.post("/api/v1/training/runs", json={"class_names": ["battery"], "input_size": "1536x864"})
    assert res.status_code == 422
    res = client.post("/api/v1/training/runs", json={"class_names": ["nope"], "input_size": "1536x864"})
    assert res.status_code == 422
