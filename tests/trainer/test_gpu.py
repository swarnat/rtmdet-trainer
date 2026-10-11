"""GPU probe used by the trainer healthcheck."""
from __future__ import annotations

import subprocess

from trainer import gpu


def fake_run(returncode: int, stdout: str = "", stderr: str = ""):
    return lambda *a, **kw: subprocess.CompletedProcess(a, returncode, stdout, stderr)


def test_probe_finds_gpu(monkeypatch):
    monkeypatch.setattr(gpu.subprocess, "run", fake_run(0, "GPU 0: NVIDIA GeForce RTX 3070 Ti Laptop GPU (UUID: GPU-83133cae)\n"))
    status = gpu.probe_gpu()
    assert status["available"] and status["devices"] == ["NVIDIA GeForce RTX 3070 Ti Laptop GPU"] and status["error"] is None


def test_probe_reports_lost_gpu(monkeypatch):
    # what a WSL2 container that lost its GPU prints
    monkeypatch.setattr(gpu.subprocess, "run", fake_run(255, "", "Failed to initialize NVML: GPU access blocked by the operating system\n"))
    status = gpu.probe_gpu()
    assert not status["available"] and "GPU access blocked" in status["error"]


def test_probe_without_nvidia_runtime(monkeypatch):
    def missing(*a, **kw):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(gpu.subprocess, "run", missing)
    assert gpu.probe_gpu()["error"].startswith("nvidia-smi not found")
