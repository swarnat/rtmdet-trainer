"""Backup endpoints: list, start (queued for the backup service), download, delete."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from odbackup.core import StatusFile, exclusive

from app.api.routes import backups
from app.main import app


@pytest.fixture()
def backup_dir(tmp_path, monkeypatch):
    path = tmp_path / "backups"
    path.mkdir()
    monkeypatch.setattr(backups, "_dir", lambda: str(path))
    return path


@pytest.fixture()
def queued(monkeypatch):
    names: list[str] = []
    monkeypatch.setattr(backups, "enqueue", names.append)
    return names


@pytest.fixture()
def client():
    return TestClient(app)


def completed(backup_dir, name: str, data: bytes = b"tar-data") -> None:
    (backup_dir / f"{name}.tar").write_bytes(data)
    StatusFile(str(backup_dir), name, {"name": name, "file": f"{name}.tar", "status": "completed",
                                       "created_at": f"2026-10-0{name[-1]}T10:00:00+00:00"})


def test_start_backup_queues_job_and_lists_it(client, backup_dir, queued):
    res = client.post("/api/v1/backups")

    assert res.status_code == 202
    name = res.json()["name"]
    assert queued == [name] and name.startswith("backup-")
    listing = client.get("/api/v1/backups").json()
    assert listing["available"] is True and listing["free_bytes"] > 0
    assert [(b["name"], b["status"]) for b in listing["backups"]] == [(name, "queued")]
    # only one at a time
    assert client.post("/api/v1/backups").status_code == 409


def test_start_refused_while_restore_or_backup_holds_the_lock(client, backup_dir, queued):
    with exclusive(str(backup_dir)):
        assert client.get("/api/v1/backups").json()["busy"] is True
        assert client.post("/api/v1/backups").status_code == 409
    assert queued == []


def test_queue_unavailable_leaves_no_entry(client, backup_dir, monkeypatch):
    def fail(_name):
        raise ConnectionError("redis down")

    monkeypatch.setattr(backups, "enqueue", fail)
    assert client.post("/api/v1/backups").status_code == 503
    assert client.get("/api/v1/backups").json()["backups"] == []


def test_download_and_delete(client, backup_dir):
    completed(backup_dir, "backup-1", b"0123456789")
    completed(backup_dir, "backup-2")

    res = client.get("/api/v1/backups/backup-1/download")
    assert res.status_code == 200 and res.content == b"0123456789"
    assert 'filename="backup-1.tar"' in res.headers["content-disposition"]

    assert client.delete("/api/v1/backups/backup-1").status_code == 204
    assert sorted(os.listdir(backup_dir)) == ["backup-2.json", "backup-2.tar"]
    assert client.delete("/api/v1/backups/backup-1").status_code == 404


def test_running_backup_cannot_be_deleted_or_downloaded(client, backup_dir):
    StatusFile(str(backup_dir), "backup-3", {"name": "backup-3", "status": "running", "created_at": "2026-10-04T10:00:00+00:00"})
    assert client.delete("/api/v1/backups/backup-3").status_code == 409
    assert client.get("/api/v1/backups/backup-3/download").status_code == 409


def test_invalid_name(client, backup_dir):
    assert client.delete("/api/v1/backups/..%2Fetc").status_code in (404, 422)
    assert client.get("/api/v1/backups/x.tar/download").status_code == 422
