"""Client annotator fixtures: data directory in tmp, fake inference server via httpx.MockTransport."""
from __future__ import annotations

import os

TOKEN = "client-token-0123456789"
os.environ["CLIENT_ACCESS_TOKEN"] = TOKEN
os.environ["STATIC_DIR"] = "/nonexistent"

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

CONFIG = {
    "classes": [{"name": "person", "label": "Person", "color": "#ff0000"}, {"name": "vehicle", "label": "Fahrzeug", "color": "#00ff00"}],
    "inference_url": "http://inference.local:8100/",
    "confidence": 0.3,
}


def jpeg(seed: int = 1, w: int = 160, h: int = 120) -> bytes:
    image = np.random.default_rng(seed).integers(0, 255, (h, w, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


class FakeInference:
    """Records requests, answers like inference-server's POST /api/v1/detect."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.response = httpx.Response(200, json={
            "model": {"version": "model-0007", "architecture": "rtmdet-s", "class_names": ["person", "vehicle"],
                      "input_width": 1536, "input_height": 864, "installed_at": None},
            "image": {"width": 160, "height": 120},
            "confidence_threshold": 0.3,
            "inference_ms": 12.5,
            "categories": [{"class": "person", "count": 1, "max_confidence": 0.9}],
            "detections": [{"class": "person", "confidence": 0.9, "bbox": {"x1": 10, "y1": 20, "x2": 50, "y2": 100}}],
        })

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.response


@pytest.fixture()
def inference(monkeypatch):
    from app import main

    fake = FakeInference()
    monkeypatch.setattr(main, "inference_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    return fake


@pytest.fixture()
def raw_client(tmp_path, monkeypatch):
    """Client without credentials."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture()
def client(raw_client):
    raw_client.headers["Authorization"] = f"Bearer {TOKEN}"
    return raw_client


@pytest.fixture()
def configured(client):
    assert client.put("/api/v1/config", json=CONFIG).status_code == 200
    return client
