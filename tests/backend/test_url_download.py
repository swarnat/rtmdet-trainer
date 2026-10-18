"""Batch download: images from URLs are stored like uploads."""
from __future__ import annotations

from contextlib import contextmanager

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from odcore.db import Image

from app.core.database import get_db
from app.core.s3 import get_storage
from app.main import app
from app.services import url_download


def jpeg(seed: int = 1) -> bytes:
    image = np.random.default_rng(seed).integers(0, 255, (120, 160, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


class MemoryStorage:
    class settings:  # noqa: N801 - mimics S3Settings attributes
        bucket_images = "training-images"

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data


PAGES = {
    "http://cam.local/a/bild%201.jpg": (200, jpeg(1)),
    "http://cam.local/b.jpg": (200, jpeg(2)),
    "http://cam.local/missing.jpg": (404, b"not found"),
    "http://cam.local/page.html": (200, b"<html></html>"),
}


@pytest.fixture()
def env(session_factory, monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        code, body = PAGES.get(str(req.url), (404, b""))
        return httpx.Response(code, content=body)

    transport = httpx.MockTransport(handler)

    @contextmanager
    def stream(method, url, **kw):
        with httpx.Client(transport=transport) as client, client.stream(method, url, headers=kw.get("headers")) as res:
            yield res

    monkeypatch.setattr(httpx, "stream", stream)
    storage = MemoryStorage()

    def db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_storage] = lambda: storage
    yield TestClient(app), session_factory, storage
    app.dependency_overrides.clear()


def post(client, url):
    res = client.post("/api/v1/images/from-url", json={"url": url})
    assert res.status_code == 200
    return res.json()


def test_download_creates_unlabeled_image(env):
    client, session_factory, storage = env
    r = post(client, " http://cam.local/a/bild%201.jpg ")
    assert r["status"] == "created"
    assert r["filename"] == "bild 1.jpg"
    assert r["image"]["annotation_status"] == "unlabeled"
    assert (r["image"]["width"], r["image"]["height"]) == (160, 120)
    with session_factory() as s:
        assert s.query(Image).count() == 1
    assert any(k.startswith("thumbnails/") for k in storage.objects)
    # the same content again is a duplicate
    assert post(client, "http://cam.local/a/bild%201.jpg")["status"] == "duplicate"


@pytest.mark.parametrize(
    "url, error",
    [
        ("http://cam.local/missing.jpg", "HTTP 404"),
        ("http://cam.local/page.html", "unsupported image format"),
        ("ftp://cam.local/x.jpg", "only http(s)"),
    ],
)
def test_download_errors_are_reported_per_url(env, url, error):
    client, session_factory, _ = env
    r = post(client, url)
    assert r["status"] == "error"
    assert error in r["error"]
    with session_factory() as s:
        assert s.query(Image).count() == 0


def test_download_respects_size_limit(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setattr(url_download, "get_settings", lambda: type("S", (), {"max_upload_mb": 0, "download_proxy": None})())
    r = post(client, "http://cam.local/b.jpg")
    assert r["status"] == "error" and "exceeds" in r["error"]


@pytest.mark.parametrize("configured, expected", [("http://proxy.local:8888", "http://proxy.local:8888"), ("", None)])
def test_download_uses_configured_proxy(env, monkeypatch, configured, expected):
    client, _, _ = env
    monkeypatch.setattr(url_download, "get_settings", lambda: type("S", (), {"max_upload_mb": 50, "download_proxy": configured})())
    mocked, proxies = httpx.stream, []

    def stream(method, url, **kw):
        proxies.append(kw.get("proxy"))
        return mocked(method, url, **kw)

    monkeypatch.setattr(httpx, "stream", stream)
    assert post(client, "http://cam.local/b.jpg")["status"] == "created"
    assert proxies == [expected]
