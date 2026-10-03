"""Rollout of a model version to the production detection API (``inference-server``).

The production system receives the OpenVINO IR plus a manifest (version, classes,
input size, NMS threshold) via ``PUT /api/v1/model`` and replaces its active model
once the upload compiled and test-ran successfully.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from odcore.db import ModelVersion, utcnow
from odcore.settings_store import get_setting
from odcore.storage import ObjectStorage

log = logging.getLogger(__name__)

UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=10.0)
STATUS_TIMEOUT = httpx.Timeout(5.0)


class DeploymentError(RuntimeError):
    pass


class NotConfiguredError(DeploymentError):
    pass


@dataclass(frozen=True)
class Target:
    url: str
    access_key: str


def http_client(timeout: httpx.Timeout) -> httpx.Client:
    """Separate function so tests can substitute the transport."""
    return httpx.Client(timeout=timeout)


def get_target(session: Session) -> Optional[Target]:
    url = str(get_setting(session, "deployment_url") or "").rstrip("/")
    key = str(get_setting(session, "deployment_access_key") or "")
    return Target(url, key) if url and key else None


def build_manifest(mv: ModelVersion, nms_iou_threshold: float) -> dict[str, Any]:
    overall = (mv.metrics_json or {}).get("overall")
    return {
        "version": mv.version,
        "class_names": list(mv.class_names),
        "input_width": mv.input_width,
        "input_height": mv.input_height,
        "nms_iou_threshold": nms_iou_threshold,
        "architecture": mv.architecture,
        "metrics": {"overall": overall} if overall else None,
        "exported_at": utcnow().isoformat(),
    }


def _detail(res: httpx.Response) -> str:
    try:
        detail = res.json().get("detail")
    except Exception:
        detail = None
    return str(detail or res.text[:300] or res.reason_phrase)


def deploy(session: Session, storage: ObjectStorage, mv: ModelVersion) -> dict[str, Any]:
    target = get_target(session)
    if target is None:
        raise NotConfiguredError("production system not configured (settings: deployment_url, deployment_access_key)")
    manifest = build_manifest(mv, float(get_setting(session, "nms_iou_threshold")))
    bucket = storage.settings.bucket_models
    bin_key = mv.openvino_key[: -len(".xml")] + ".bin"
    session.close()  # no DB connection needed during the (possibly long) upload

    with tempfile.TemporaryDirectory(prefix="od-deploy-") as tmp:
        xml_path, bin_path = os.path.join(tmp, "model.xml"), os.path.join(tmp, "model.bin")
        storage.download_file(bucket, mv.openvino_key, xml_path)
        storage.download_file(bucket, bin_key, bin_path)
        log.info("uploading model %s to %s", mv.version, target.url)
        try:
            with open(xml_path, "rb") as fx, open(bin_path, "rb") as fb, http_client(UPLOAD_TIMEOUT) as client:
                res = client.put(
                    f"{target.url}/api/v1/model",
                    headers={"X-Access-Key": target.access_key},
                    data={"manifest": json.dumps(manifest)},
                    files={"model_xml": ("model.xml", fx, "application/xml"), "model_bin": ("model.bin", fb, "application/octet-stream")},
                )
        except httpx.HTTPError as exc:
            raise DeploymentError(f"production system not reachable at {target.url}: {exc}") from exc
    if res.status_code != 200:
        log.warning("production system rejected model %s (HTTP %s): %s", mv.version, res.status_code, _detail(res))
        raise DeploymentError(f"production system rejected the model (HTTP {res.status_code}): {_detail(res)}")
    log.info("model %s is now active on %s", mv.version, target.url)
    return res.json()


def status(session: Session) -> dict[str, Any]:
    """What the production system currently runs (never raises)."""
    target = get_target(session)
    session.close()
    if target is None:
        return {"configured": False, "url": None, "reachable": False, "model": None, "error": None}
    result: dict[str, Any] = {"configured": True, "url": target.url, "reachable": False, "model": None, "error": None}
    try:
        with http_client(STATUS_TIMEOUT) as client:
            res = client.get(f"{target.url}/api/v1/model")
    except httpx.HTTPError as exc:
        result["error"] = f"not reachable: {exc.__class__.__name__}"
        return result
    result["reachable"] = True
    if res.status_code == 200:
        result["model"] = res.json()
    elif res.status_code != 404:  # 404 = reachable, but no model installed yet
        result["error"] = f"HTTP {res.status_code}: {_detail(res)}"
    return result
