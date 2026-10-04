"""Production detection API: detection response, minimum confidence, authenticated model replacement."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import ACCESS_KEY, build_constant_model, image_file, upload


def test_without_model_detect_is_unavailable(client):
    health = client.get("/api/v1/health").json()
    assert (health["model_loaded"], health["model_version"], health["uploads_enabled"]) == (False, None, True)
    assert client.post("/api/v1/detect", files=image_file()).status_code == 503
    assert client.get("/api/v1/model").status_code == 404


def test_detect_returns_detections_and_categories(client, model_files):
    assert upload(client, model_files).status_code == 200

    res = client.post("/api/v1/detect", files=image_file())

    assert res.status_code == 200
    body = res.json()
    assert body["model"]["version"] == "model-0007"
    assert body["image"] == {"width": 1920, "height": 1080}
    assert body["confidence_threshold"] == 0.15
    # bicycle (0.12) is below the minimum confidence, the duplicate person is removed by NMS
    assert [d["class"] for d in body["detections"]] == ["person", "vehicle", "vehicle"]
    assert [d["confidence"] for d in body["detections"]] == pytest.approx([0.9, 0.6, 0.4], abs=1e-3)
    assert [(c["class"], c["count"]) for c in body["categories"]] == [("person", 1), ("vehicle", 2)]
    assert [c["max_confidence"] for c in body["categories"]] == pytest.approx([0.9, 0.6], abs=1e-3)
    # boxes are in pixels of the uploaded 1920x1080 image (model input 1536x864 -> factor 1.25)
    assert body["detections"][0]["bbox"] == {"x1": 500, "y1": 200, "x2": 700, "y2": 800}


def test_confidence_cannot_go_below_minimum(client, model_files):
    upload(client, model_files)
    assert client.post("/api/v1/detect", files=image_file(), data={"confidence": "0.1"}).status_code == 422
    res = client.post("/api/v1/detect", files=image_file(), data={"confidence": "0.5"})
    assert [d["class"] for d in res.json()["detections"]] == ["person", "vehicle"]


def test_upload_requires_the_access_key(client, model_files):
    assert upload(client, model_files, key=None).status_code == 401
    assert upload(client, model_files, key="wrong-key-wrong-key").status_code == 401
    assert client.get("/api/v1/model").status_code == 404
    xml, weights = model_files
    with open(xml, "rb") as fx, open(weights, "rb") as fb:
        res = client.put("/api/v1/model", headers={"Authorization": f"Bearer {ACCESS_KEY}"},
                         data={"manifest": '{"version": "model-0001", "class_names": ["person", "bicycle", "vehicle"], '
                                           '"input_width": 1536, "input_height": 864}'},
                         files={"model_xml": ("model.xml", fx), "model_bin": ("model.bin", fb)})
    assert res.status_code == 200


def test_new_upload_replaces_active_model_and_removes_old_files(client, model_files, model_dir):
    upload(client, model_files, version="model-0001")
    assert upload(client, model_files, version="model-0002").status_code == 200

    assert client.get("/api/v1/model").json()["version"] == "model-0002"
    assert client.post("/api/v1/detect", files=image_file()).json()["model"]["version"] == "model-0002"
    dirs = [p.name for p in model_dir.iterdir() if p.is_dir()]
    assert len(dirs) == 1 and dirs[0].startswith("model-0002-")


def test_invalid_model_keeps_previous_model(client, model_files, tmp_path):
    upload(client, model_files, version="model-0001")

    # class list does not match the model's score columns
    assert upload(client, model_files, version="model-0002", classes=["person"]).status_code == 422
    # corrupt files
    bad = tmp_path / "bad.xml"
    bad.write_text("not a model")
    assert upload(client, (str(bad), str(bad)), version="model-0003").status_code == 422

    assert client.get("/api/v1/model").json()["version"] == "model-0001"
    assert client.post("/api/v1/detect", files=image_file()).status_code == 200


def test_installed_model_survives_restart(model_dir, model_files):
    from app.main import app

    with TestClient(app) as first:
        upload(first, model_files, version="model-0005")
    with TestClient(app) as second:
        assert second.get("/api/v1/model").json()["version"] == "model-0005"
        assert second.post("/api/v1/detect", files=image_file()).status_code == 200


def test_uploads_disabled_without_key(model_dir, model_files, monkeypatch):
    from app.config import get_settings
    from app.main import app

    monkeypatch.setenv("MODEL_UPLOAD_KEY", "short")
    get_settings.cache_clear()
    with TestClient(app) as c:
        assert c.get("/api/v1/health").json()["uploads_enabled"] is False
        assert upload(c, model_files, key="short").status_code == 503


def test_model_with_more_classes(client, tmp_path):
    scores = np.zeros((5, 4), np.float32)
    scores[0, 3] = 0.8
    xml = build_constant_model(str(tmp_path / "four" / "model.xml"), scores)
    res = upload(client, (xml, xml[:-4] + ".bin"), classes=["person", "bicycle", "vehicle", "battery"])
    assert res.status_code == 200
    assert client.post("/api/v1/detect", files=image_file()).json()["categories"][0]["class"] == "battery"
