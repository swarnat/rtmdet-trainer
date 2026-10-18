"""Connection to the client annotator (``client-annotator/``) on a customer server.

The training system pushes the configuration (active classes, inference server, confidence) and imports the
images with their annotations one by one; each imported image is deleted on the client afterwards, so the next
batch can be prepared there. Requests go through DEPLOYMENT_PROXY (the customer network of the production system).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from odcore.classes import list_classes
from odcore.settings_store import get_setting

from app.core.config import get_settings

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(60.0, connect=10.0)
STATUS_TIMEOUT = httpx.Timeout(5.0)


class ClientAnnotatorError(RuntimeError):
    pass


class NotConfiguredError(ClientAnnotatorError):
    pass


@dataclass(frozen=True)
class Target:
    url: str
    access_key: str


def http_client(timeout: httpx.Timeout) -> httpx.Client:
    """Separate function so tests can substitute the transport."""
    return httpx.Client(timeout=timeout, proxy=get_settings().deployment_proxy or None)


def get_target(session: Session) -> Optional[Target]:
    url = str(get_setting(session, "client_annotator_url") or "").rstrip("/")
    key = str(get_setting(session, "client_annotator_access_key") or "")
    return Target(url, key) if url and key else None


def require_target(session: Session) -> Target:
    target = get_target(session)
    if target is None:
        raise NotConfiguredError("client annotator not configured (settings: client_annotator_url, client_annotator_access_key)")
    return target


def _detail(res: httpx.Response) -> str:
    try:
        detail = res.json().get("detail")
    except Exception:
        detail = None
    return str(detail or res.text[:300] or res.reason_phrase)


def _request(target: Target, method: str, path: str, timeout: httpx.Timeout = TIMEOUT, **kwargs: Any) -> httpx.Response:
    try:
        with http_client(timeout) as client:
            res = client.request(method, f"{target.url}/api/v1{path}", headers={"X-Access-Key": target.access_key}, **kwargs)
    except httpx.HTTPError as exc:
        raise ClientAnnotatorError(f"client annotator not reachable at {target.url}: {exc.__class__.__name__}") from exc
    if res.status_code >= 400:
        raise ClientAnnotatorError(f"client annotator: HTTP {res.status_code}: {_detail(res)}")
    return res


def build_config(session: Session) -> dict[str, Any]:
    inference_url = str(get_setting(session, "client_inference_url") or get_setting(session, "deployment_url") or "")
    return {
        "classes": [{"name": c.name, "label": c.label, "color": c.color} for c in list_classes(session, active_only=True)],
        "inference_url": inference_url.rstrip("/"),
        "confidence": float(get_setting(session, "default_confidence")),
        "source": "training system",
    }


def push_config(session: Session) -> dict[str, Any]:
    target = require_target(session)
    config = build_config(session)
    if not config["classes"]:
        raise ClientAnnotatorError("no active classes to push")
    res = _request(target, "PUT", "/config", json=config)
    log.info("pushed configuration (%d classes) to the client annotator at %s", len(config["classes"]), target.url)
    return res.json()


def status(session: Session) -> dict[str, Any]:
    """Configuration and image counts of the client annotator (never raises)."""
    target = get_target(session)
    if target is None:
        return {"configured": False, "url": None, "reachable": False, "error": None, "config": None, "counts": None}
    result: dict[str, Any] = {"configured": True, "url": target.url, "reachable": False, "error": None, "config": None, "counts": None}
    try:
        result["config"] = _request(target, "GET", "/config", STATUS_TIMEOUT).json()
        result["counts"] = _request(target, "GET", "/images", STATUS_TIMEOUT, params={"limit": 0}).json()["counts"]
        result["reachable"] = True
    except ClientAnnotatorError as exc:
        result["error"] = str(exc)
    return result


def list_images(target: Target) -> dict[str, Any]:
    return _request(target, "GET", "/images").json()


def get_image(target: Target, image_id: int) -> dict[str, Any]:
    return _request(target, "GET", f"/images/{image_id}").json()


def get_file(target: Target, image_id: int) -> bytes:
    return _request(target, "GET", f"/images/{image_id}/file").content


def delete_image(target: Target, image_id: int) -> None:
    _request(target, "DELETE", f"/images/{image_id}")
