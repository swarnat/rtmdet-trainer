"""Backups: list, request (runs asynchronously in the backup service), download, delete.

Restoring is only possible on the command line (``make restore FILE=…``), because it replaces
the database and all buckets while API and trainer are stopped.
"""
from __future__ import annotations

import logging
import os
import shutil
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from odbackup.core import BackupError, StatusFile, check_name, is_busy, list_backups, new_name, utcnow
from odbackup.jobs import QUEUE, job_id

from app.core.config import get_settings
from app.core.queue import get_redis

log = logging.getLogger(__name__)
router = APIRouter(prefix="/backups", tags=["backups"])
ACTIVE = ("queued", "running")


def _dir() -> str:
    return get_settings().backup_dir


def enqueue(name: str) -> None:
    """Hand the backup to the backup service (the job function only exists there); no timeout."""
    from rq import Queue

    Queue(QUEUE, connection=get_redis()).enqueue(
        "odbackup.jobs.create_backup_job", name, job_id=job_id(name), job_timeout=-1,
        result_ttl=86400, failure_ttl=7 * 86400,
    )


def _get(name: str) -> dict[str, Any]:
    try:
        check_name(name)
    except BackupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for item in list_backups(_dir()):
        if item["name"] == name:
            return item
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"backup '{name}' not found")


@router.get("", summary="Backups in the backup folder, newest first")
def get_backups() -> dict[str, Any]:
    directory = _dir()
    if not os.path.isdir(directory):
        return {"backups": [], "busy": False, "free_bytes": None, "available": False}
    return {
        "backups": list_backups(directory),
        "busy": is_busy(directory),
        "free_bytes": shutil.disk_usage(directory).free,
        "available": True,
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED, summary="Start a full backup (asynchronous, no timeout)")
def start_backup() -> dict[str, Any]:
    directory = _dir()
    if not os.path.isdir(directory):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"backup folder {directory} is not mounted")
    if is_busy(directory) or any(i.get("status") in ACTIVE for i in list_backups(directory)):
        raise HTTPException(status.HTTP_409_CONFLICT, "a backup or restore is already running")
    name = new_name()
    entry = StatusFile(directory, name, {"name": name, "file": f"{name}.tar", "status": "queued", "source": "ui",
                                         "created_at": utcnow(), "error": None, "warnings": []})
    try:
        enqueue(name)
    except Exception as exc:
        os.remove(entry.path)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"job queue unavailable: {exc}") from exc
    log.info("backup %s queued", name)
    return entry.data


@router.get("/{name}/download", summary="Download a backup file")
def download_backup(name: str) -> FileResponse:
    item = _get(name)
    if item.get("status") != "completed" or not item.get("file_exists"):
        raise HTTPException(status.HTTP_409_CONFLICT, "backup is not complete")
    return FileResponse(os.path.join(_dir(), f"{name}.tar"), media_type="application/x-tar", filename=f"{name}.tar")


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a backup")
def delete_backup(name: str) -> Response:
    item = _get(name)
    if item.get("status") in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "the backup is still running")
    for suffix in (".tar", ".json"):
        path = os.path.join(_dir(), f"{name}{suffix}")
        if os.path.exists(path):
            os.remove(path)
    log.info("backup %s deleted", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
