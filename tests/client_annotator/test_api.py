"""Client annotator API: token, configuration push, images, annotations, check against the inference server."""
from __future__ import annotations

import httpx
import pytest

from conftest import CONFIG, TOKEN, jpeg


def upload(client, *files: bytes) -> list[dict]:
    res = client.post("/api/v1/images", files=[("files", (f"bild{i}.jpg", data, "image/jpeg")) for i, data in enumerate(files)])
    assert res.status_code == 200
    return res.json()


def test_health_without_token(raw_client):
    res = raw_client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "token_configured": True, "configured": False}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-token-0123456789"}, {"X-Access-Key": "nope"}])
def test_api_requires_token(raw_client, headers):
    for method, path in (("get", "/api/v1/images"), ("get", "/api/v1/config"), ("delete", "/api/v1/images/1")):
        assert getattr(raw_client, method)(path, headers=headers).status_code == 401


def test_x_access_key_and_login_cookie(raw_client):
    assert raw_client.get("/api/v1/images", headers={"X-Access-Key": TOKEN}).status_code == 200
    assert raw_client.post("/api/v1/session", json={"token": "wrong"}).status_code == 401
    assert raw_client.post("/api/v1/session", json={"token": TOKEN}).status_code == 204
    assert raw_client.get("/api/v1/images").status_code == 200  # cookie
    assert raw_client.delete("/api/v1/session").status_code == 204
    raw_client.cookies.clear()
    assert raw_client.get("/api/v1/images").status_code == 401


def test_config_push(client):
    assert client.get("/api/v1/config").json() is None
    res = client.put("/api/v1/config", json=CONFIG)
    assert res.status_code == 200
    body = res.json()
    assert body["inference_url"] == "http://inference.local:8100"  # trailing slash removed
    assert body["pushed_at"]
    assert client.get("/api/v1/config").json() == body
    assert client.get("/api/v1/health").json()["configured"] is True
    dup = {**CONFIG, "classes": CONFIG["classes"] + [CONFIG["classes"][0]]}
    assert client.put("/api/v1/config", json=dup).status_code == 422
    assert client.put("/api/v1/config", json={**CONFIG, "inference_url": "ftp://x"}).status_code == 422


def test_upload_dedupes_and_serves_files(client):
    r = upload(client, jpeg(1), jpeg(1), b"no image")
    assert [x["status"] for x in r] == ["created", "duplicate", "error"]
    image = r[0]["image"]
    assert (image["width"], image["height"], image["status"]) == (160, 120, "open")
    assert client.get(f"/api/v1/images/{image['id']}/file").content == jpeg(1)
    assert client.get(f"/api/v1/images/{image['id']}/thumbnail").headers["content-type"] == "image/jpeg"
    assert client.get("/api/v1/images").json()["counts"] == {"total": 1, "open": 1, "annotated": 0}
    assert client.get("/api/v1/images?limit=0").json() == {"counts": {"total": 1, "open": 1, "annotated": 0}, "items": []}


def test_download_from_url(client, monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=jpeg(3)) if req.url.raw_path == b"/a/cam%201.jpg" else httpx.Response(404)

    real_client = httpx.Client
    from contextlib import contextmanager

    @contextmanager
    def stream(method, url, **kw):
        with real_client(transport=httpx.MockTransport(handler)) as c, c.stream(method, url) as res:
            yield res

    monkeypatch.setattr(httpx, "stream", stream)
    ok = client.post("/api/v1/images/from-url", json={"url": " http://cam.local/a/cam%201.jpg "}).json()
    assert ok["status"] == "created" and ok["filename"] == "cam 1.jpg"
    assert ok["image"]["source_url"] == "http://cam.local/a/cam%201.jpg"
    missing = client.post("/api/v1/images/from-url", json={"url": "http://cam.local/missing.jpg"}).json()
    assert missing["status"] == "error" and "HTTP 404" in missing["error"]


def test_annotations_need_config_and_known_classes(client):
    image = upload(client, jpeg(1))[0]["image"]
    box = {"class": "person", "x1": 10, "y1": 10, "x2": 60, "y2": 90}
    assert client.put(f"/api/v1/images/{image['id']}/annotations", json={"annotations": [box]}).status_code == 409
    client.put("/api/v1/config", json=CONFIG)
    res = client.put(f"/api/v1/images/{image['id']}/annotations", json={"annotations": [{**box, "class": "dog"}]})
    assert res.status_code == 422 and "unknown class" in res.json()["detail"]


def test_save_annotations_and_reopen(configured):
    image = upload(configured, jpeg(1))[0]["image"]
    boxes = [
        {"class": "person", "x1": 60, "y1": 90, "x2": 10, "y2": 10, "source": "prediction"},  # swapped corners
        {"class": "vehicle", "x1": 100, "y1": 10, "x2": 200, "y2": 50, "type": "hard_negative",
         "source": "prediction", "source_confidence": 0.4, "source_model": "model-0007"},  # clipped to the image
    ]
    res = configured.put(f"/api/v1/images/{image['id']}/annotations", json={"annotations": boxes})
    assert res.status_code == 200
    saved = res.json()
    assert saved["status"] == "annotated" and saved["annotated_at"]
    assert saved["annotations"][0] == {"class": "person", "x1": 10.0, "y1": 10.0, "x2": 60.0, "y2": 90.0, "type": "positive",
                                       "reflected": False, "source": "prediction", "source_confidence": None, "source_model": None}
    assert saved["annotations"][1]["x2"] == 160.0 and saved["annotations"][1]["source_confidence"] == 0.4
    assert configured.get("/api/v1/images?status=annotated").json()["counts"]["annotated"] == 1
    reopened = configured.patch(f"/api/v1/images/{image['id']}", json={"status": "open"}).json()
    assert reopened["status"] == "open" and len(reopened["annotations"]) == 2
    draft = configured.put(f"/api/v1/images/{image['id']}/annotations", json={"annotations": [], "mark_annotated": False}).json()
    assert draft["status"] == "open" and draft["annotations"] == []


def test_detect_against_inference_server(configured, inference):
    image = upload(configured, jpeg(1))[0]["image"]
    res = configured.post(f"/api/v1/images/{image['id']}/detect", json={})
    assert res.status_code == 200
    det = res.json()["detection"]
    assert det["model_version"] == "model-0007" and (det["input_width"], det["input_height"]) == (1536, 864)
    assert det["confidence"] == 0.3
    assert det["detections"] == [{"class": "person", "confidence": 0.9, "bbox": {"x1": 10, "y1": 20, "x2": 50, "y2": 100}}]
    req = inference.requests[0]
    assert str(req.url) == "http://inference.local:8100/api/v1/detect"
    assert b'name="confidence"\r\n\r\n0.3' in req.content and jpeg(1) in req.content
    configured.post(f"/api/v1/images/{image['id']}/detect", json={"confidence": 0.5})
    assert b'name="confidence"\r\n\r\n0.5' in inference.requests[1].content


def test_detect_errors(configured, inference):
    image = upload(configured, jpeg(1))[0]["image"]
    inference.response = httpx.Response(503, json={"detail": "no model installed yet"})
    res = configured.post(f"/api/v1/images/{image['id']}/detect")
    assert res.status_code == 502 and "no model installed yet" in res.json()["detail"]
    configured.put("/api/v1/config", json={**CONFIG, "inference_url": ""})
    assert configured.post(f"/api/v1/images/{image['id']}/detect").status_code == 409


def test_delete_removes_files(configured, tmp_path):
    image = upload(configured, jpeg(1))[0]["image"]
    assert configured.delete(f"/api/v1/images/{image['id']}").status_code == 204
    assert configured.delete(f"/api/v1/images/{image['id']}").status_code == 404
    assert list((tmp_path / "data" / "images").iterdir()) == []
    assert list((tmp_path / "data" / "thumbnails").iterdir()) == []
    # the same image can be loaded again afterwards (next batch)
    assert upload(configured, jpeg(1))[0]["status"] == "created"


def test_check_confidence_from_env_overrides_pushed_value(configured, inference, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("CHECK_CONFIDENCE", "0.55")
    get_settings.cache_clear()
    config = configured.get("/api/v1/config").json()
    assert (config["confidence"], config["confidence_source"], config["pushed_confidence"]) == (0.55, "env", 0.3)
    # a new push keeps the override
    assert configured.put("/api/v1/config", json={**CONFIG, "confidence": 0.2}).json()["confidence"] == 0.55
    image = upload(configured, jpeg(1))[0]["image"]
    configured.post(f"/api/v1/images/{image['id']}/detect")
    assert b'name="confidence"\r\n\r\n0.55' in inference.requests[-1].content
    # an explicit value of the request (slider in the web UI) still wins
    configured.post(f"/api/v1/images/{image['id']}/detect", json={"confidence": 0.7})
    assert b'name="confidence"\r\n\r\n0.7' in inference.requests[-1].content


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_check_confidence_uses_pushed_value(configured, monkeypatch, value):
    from app.config import get_settings

    monkeypatch.setenv("CHECK_CONFIDENCE", value)
    get_settings.cache_clear()
    config = configured.get("/api/v1/config").json()
    assert (config["confidence"], config["confidence_source"]) == (0.3, "pushed")


def test_ignore_regions_and_reflections_are_stored(configured):
    image = upload(configured, jpeg(1))[0]["image"]
    boxes = [
        {"class": "person", "x1": 10, "y1": 10, "x2": 60, "y2": 90, "reflected": True},
        {"class": "person", "x1": 70, "y1": 10, "x2": 120, "y2": 90, "type": "ignore"},
    ]
    saved = configured.put(f"/api/v1/images/{image['id']}/annotations", json={"annotations": boxes}).json()
    assert [(a["type"], a["reflected"]) for a in saved["annotations"]] == [("positive", True), ("ignore", False)]
    assert configured.get("/api/v1/images").json()["items"][0]["annotations"] == saved["annotations"]
