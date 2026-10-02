#!/usr/bin/env python3
"""Import the COCO-pretrained RTMDet-S as a model version via the running stack.

The trainer does this automatically on first start (BOOTSTRAP_ON_START=true).
Use this script to re-import, e.g. after changing the COCO class mapping:

    python3 scripts/bootstrap-model.py --url http://localhost:8080 [--activate]

Only the Python standard library is required.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def call(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or b"null")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8080", help="frontend or API base URL")
    p.add_argument("--activate", action="store_true", help="activate the imported version as production")
    p.add_argument("--timeout", type=int, default=900, help="seconds to wait for the import")
    args = p.parse_args()
    api = args.url.rstrip("/") + "/api/v1"

    before = {m["version"] for m in call(f"{api}/models")}
    job = call(f"{api}/models/bootstrap?force=true", "POST")
    print(f"queued bootstrap job {job['job_id']}, waiting for the trainer ...")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        new = [m for m in call(f"{api}/models") if m["version"] not in before and m["kind"] == "coco-bootstrap"]
        if new:
            version = new[0]["version"]
            print(f"imported as {version} (status {new[0]['status']})")
            if args.activate and new[0]["status"] != "production":
                call(f"{api}/models/{version}/activate", "POST")
                print(f"{version} is now production")
            return 0
        time.sleep(5)
    print("timed out - check `docker compose logs trainer`", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
