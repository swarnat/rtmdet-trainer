"""GPU requirement: training only runs on an NVIDIA GPU (CUDA).

``python -m trainer.gpu`` is the container healthcheck: it probes the GPU with
``nvidia-smi`` (no CUDA context, so it cannot disturb a running training),
publishes the result in Redis for the API (``trainer:gpu``, expires when the
trainer stops reporting) and exits non-zero without a GPU. Under WSL2 a running
container can lose GPU access (e.g. Windows driver update, sleep); only a
re-created container gets it back.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

GPU_STATUS_KEY = "trainer:gpu"
GPU_STATUS_TTL = 120  # seconds; healthcheck interval is 30 s

NO_GPU_HINT = (
    "Training requires an NVIDIA GPU, but the trainer container has no CUDA access. "
    "Re-create it (docker compose up -d --force-recreate trainer) and make sure docker-compose.gpu.yml "
    "is part of COMPOSE_FILE and the NVIDIA Container Toolkit is installed."
)


def probe_gpu() -> dict:
    try:
        proc = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=20)
        output = (proc.stdout + proc.stderr).strip()
        names = [line.split(":", 1)[1].split("(UUID")[0].strip() for line in proc.stdout.splitlines() if line.startswith("GPU ")]
        ok = proc.returncode == 0 and bool(names)
        error = None if ok else (output.splitlines()[0] if output else f"nvidia-smi exited with code {proc.returncode}")
    except FileNotFoundError:
        names, ok, error = [], False, "nvidia-smi not found (container started without GPU support)"
    except subprocess.TimeoutExpired:
        names, ok, error = [], False, "nvidia-smi timed out"
    return {"available": ok, "devices": names, "error": error, "checked_at": datetime.now(timezone.utc).isoformat()}


def main() -> int:
    from redis import Redis

    status = probe_gpu()
    # also the liveness check of the Redis connection (the previous healthcheck)
    Redis.from_url(os.environ["REDIS_URL"]).set(GPU_STATUS_KEY, json.dumps(status), ex=GPU_STATUS_TTL)
    if not status["available"]:
        print(f"no GPU: {status['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
