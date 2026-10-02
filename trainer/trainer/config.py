"""Trainer configuration from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from odcore.storage import S3Settings

DEFAULT_BASE_CHECKPOINT_URL = (
    "https://download.openmmlab.com/mmdetection/v3.0/rtmdet/rtmdet_s_8xb32-300e_coco/"
    "rtmdet_s_8xb32-300e_coco_20220905_161602-387a891e.pth"
)


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class TrainerSettings:
    database_url: str = field(default_factory=lambda: os.environ["DATABASE_URL"])
    redis_url: str = field(default_factory=lambda: os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    queue: str = field(default_factory=lambda: os.environ.get("TRAINING_QUEUE", "training"))
    work_dir: str = field(default_factory=lambda: os.environ.get("TRAINER_WORK_DIR", "/tmp/od-work"))
    base_checkpoint_url: str = field(
        default_factory=lambda: os.environ.get("BASE_CHECKPOINT_URL", DEFAULT_BASE_CHECKPOINT_URL)
    )
    # First 8 hex chars of the checkpoint's sha256 (OpenMMLab naming convention); empty disables the check
    base_checkpoint_sha256_prefix: str = field(
        default_factory=lambda: os.environ.get("BASE_CHECKPOINT_SHA256_PREFIX", "387a891e")
    )
    bootstrap_on_start: bool = field(default_factory=lambda: _bool("BOOTSTRAP_ON_START", True))
    s3: S3Settings = field(default_factory=S3Settings.from_env)


_settings: TrainerSettings | None = None


def get_settings() -> TrainerSettings:
    global _settings
    if _settings is None:
        _settings = TrainerSettings()
    return _settings
