"""Idempotent Garage initialisation via the admin API (v1):

1. assign a layout role to the (single) node and apply the layout
2. import the S3 access key given in S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY
3. create the buckets and grant the key read/write/owner on them

Safe to run on every start: existing state is detected and left untouched.
Standard library only, so it runs in any Python image (docker-compose.yml uses the API image).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

ADMIN_URL = os.environ.get("GARAGE_ADMIN_URL", "http://garage:3903")
ZONE = os.environ.get("GARAGE_ZONE", "dc1")
CAPACITY = int(os.environ.get("GARAGE_CAPACITY_BYTES", "100000000000"))
KEY_NAME = os.environ.get("GARAGE_KEY_NAME", "object-detection")


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"[garage-init] {name} is required")
    return value


TOKEN = require("GARAGE_ADMIN_TOKEN")
KEY_ID = require("S3_ACCESS_KEY_ID")
SECRET = require("S3_SECRET_ACCESS_KEY")
BUCKETS = [
    os.environ.get("S3_BUCKET_IMAGES", "training-images"),
    os.environ.get("S3_BUCKET_DATASETS", "datasets"),
    os.environ.get("S3_BUCKET_MODELS", "models"),
]


class ApiError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[garage-init] {msg}", flush=True)


def api(method: str, path: str, data: Optional[Any] = None) -> Any:
    """Call the admin API; raises ApiError on HTTP >= 400 or connection errors."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(ADMIN_URL + path, data=body, method=method, headers={"Authorization": f"Bearer {TOKEN}"})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ApiError(f"{method} {path}: {exc}") from exc
    return json.loads(raw) if raw else None


def wait_for(what: str, check) -> Any:
    for _ in range(60):
        try:
            result = check()
            if result:
                return result
        except ApiError:
            pass
        time.sleep(2)
    sys.exit(f"[garage-init] {what}")


def main() -> None:
    log(f"waiting for admin API at {ADMIN_URL}")
    node_id = wait_for("admin API not reachable", lambda: api("GET", "/v1/status")["node"])
    log(f"node id: {node_id}")

    # 1) layout
    if not any(r["id"] == node_id for r in api("GET", "/v1/layout")["roles"]):
        log(f"assigning layout role (zone {ZONE}, capacity {CAPACITY} bytes)")
        api("POST", "/v1/layout", [{"id": node_id, "zone": ZONE, "capacity": CAPACITY, "tags": ["local"]}])
        version = api("GET", "/v1/layout")["version"] + 1
        api("POST", "/v1/layout/apply", {"version": version})
        log(f"layout version {version} applied")
    else:
        log("layout already configured")

    # wait until the cluster is healthy (layout propagated)
    wait_for("cluster did not become healthy", lambda: api("GET", "/v1/health")["status"] == "healthy")

    # 2) access key
    try:
        api("GET", f"/v1/key?id={KEY_ID}")
        log(f"access key {KEY_ID} already present")
    except ApiError:
        log(f"importing access key {KEY_ID}")
        api("POST", "/v1/key/import", {"accessKeyId": KEY_ID, "secretAccessKey": SECRET, "name": KEY_NAME})

    # 3) buckets + permissions
    for bucket in BUCKETS:
        try:
            info = api("GET", f"/v1/bucket?globalAlias={bucket}")
            log(f"bucket {bucket} exists")
        except ApiError:
            log(f"creating bucket {bucket}")
            info = api("POST", "/v1/bucket", {"globalAlias": bucket})
        api("POST", "/v1/bucket/allow", {
            "bucketId": info["id"], "accessKeyId": KEY_ID,
            "permissions": {"read": True, "write": True, "owner": True},
        })

    log("done")


if __name__ == "__main__":
    main()
