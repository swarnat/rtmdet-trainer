"""Jobs executed by the backup worker (RQ queue ``backup``, enqueued by the API without timeout)."""
from __future__ import annotations

from .core import Config, create_backup
from .postgres import Postgres
from .s3 import S3

QUEUE = "backup"


def job_id(name: str) -> str:
    return f"backup-{name}"


def create_backup_job(name: str) -> dict:
    cfg = Config.from_env()
    return create_backup(cfg, S3(), Postgres(cfg.database_url), name=name, source="ui")
