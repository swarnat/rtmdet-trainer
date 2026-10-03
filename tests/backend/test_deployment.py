"""Rollout to the production detection API: settings (masked key), upload request, error handling, status."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from odcore.db import ModelStatus, ModelVersion

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services import deployment

KEY = "prod-access-key-0123456789"


class FileStorage:
    class settings:  # noqa: N801 - mimics S3Settings attributes
        bucket_models = "models"

    def download_file(self, bucket: str, key: str, path: str) -> None:
        with open(path, "wb") as f:
            f.write(f"{bucket}/{key}".encode())


@pytest.fixture()
def client(session_factory):
    with session_factory() as s:
        s.add(ModelVersion(version="model-0004", status=ModelStatus.candidate, architecture="rtmdet-m", checkpoint_key="x",
                           onnx_key="x", openvino_key="model-0004/openvino/model.xml", input_width=1536, input_height=864,
                           class_names=["person", "vehicle"], metrics_json={"overall": {"mAP50": 0.826}}))
        s.commit()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: FileStorage()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def remote(monkeypatch):
    """Fake production system: records requests, answers with ``remote.response``."""

    class Remote:
        requests: list[httpx.Request] = []
        response = httpx.Response(200, json={"version": "model-0004"})

        def handler(self, request: httpx.Request) -> httpx.Response:
            request.read()
            self.requests.append(request)
            return self.response

    r = Remote()
    r.requests = []
    monkeypatch.setattr(deployment, "http_client", lambda timeout: httpx.Client(transport=httpx.MockTransport(r.handler)))
    return r


def configure(client):
    res = client.put("/api/v1/settings", json={"values": {"deployment_url": "https://prod.example.com/", "deployment_access_key": KEY}})
    assert res.status_code == 200
    return res.json()["values"]


def test_access_key_is_write_only(client):
    values = configure(client)
    assert values["deployment_url"] == "https://prod.example.com"
    assert values["deployment_access_key"] == "********"
    assert client.get("/api/v1/settings").json()["values"]["deployment_access_key"] == "********"
    # saving the form with the mask keeps the stored key
    client.put("/api/v1/settings", json={"values": {"deployment_access_key": "********", "default_confidence": 0.3}})
    assert client.get("/api/v1/settings").json()["values"]["deployment_access_key"] == "********"


def test_deployment_settings_validation(client):
    assert client.put("/api/v1/settings", json={"values": {"deployment_url": "prod.example.com"}}).status_code == 422
    assert client.put("/api/v1/settings", json={"values": {"deployment_access_key": "short"}}).status_code == 422


def test_deploy_uploads_model_with_manifest_and_key(client, remote):
    configure(client)

    res = client.post("/api/v1/deployment", json={"version": "model-0004"})

    assert res.status_code == 200
    (req,) = remote.requests
    assert req.method == "PUT" and str(req.url) == "https://prod.example.com/api/v1/model"
    assert req.headers["X-Access-Key"] == KEY
    body = req.content.decode()
    assert "models/model-0004/openvino/model.xml" in body and "models/model-0004/openvino/model.bin" in body
    manifest = json.loads(body.split('name="manifest"')[1].split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0])
    assert manifest["version"] == "model-0004"
    assert manifest["class_names"] == ["person", "vehicle"]
    assert (manifest["input_width"], manifest["input_height"], manifest["nms_iou_threshold"]) == (1536, 864, 0.6)


def test_deploy_without_configuration(client, remote):
    assert client.post("/api/v1/deployment", json={"version": "model-0004"}).status_code == 409
    assert remote.requests == []


def test_deploy_rejected_by_production_system(client, remote):
    configure(client)
    remote.response = httpx.Response(401, json={"detail": "invalid or missing access key"})
    res = client.post("/api/v1/deployment", json={"version": "model-0004"})
    assert res.status_code == 502
    assert "invalid or missing access key" in res.json()["detail"]


def test_deploy_unknown_version(client, remote):
    configure(client)
    assert client.post("/api/v1/deployment", json={"version": "model-0099"}).status_code == 404


def test_status(client, remote):
    assert client.get("/api/v1/deployment").json()["configured"] is False
    configure(client)
    remote.response = httpx.Response(200, json={"version": "model-0003"})
    body = client.get("/api/v1/deployment").json()
    assert body["reachable"] is True and body["model"]["version"] == "model-0003"
    remote.response = httpx.Response(404, json={"detail": "no model installed yet"})
    body = client.get("/api/v1/deployment").json()
    assert body["reachable"] is True and body["model"] is None and body["error"] is None
