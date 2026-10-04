"""Backup and restore of the whole system as one tar file.

Layout of ``<name>.tar`` (PAX format, members in this order)::

    manifest.json          format, creation time, schema revision, row counts, object counts per bucket
    database.dump          pg_dump custom format: images, annotations, classes, settings, runs, model registry
    s3/images/<key>        training images and thumbnails
    s3/datasets/<key>      dataset snapshots of the training runs
    s3/models/<key>        model artifacts (checkpoints, ONNX, OpenVINO, configs)
    summary.json           what was actually written (missing objects, totals) - marks a complete file

Next to it, ``<name>.json`` holds the status and progress shown in the UI. A backup is
written as ``.<name>.tar.partial`` and renamed when complete. Only one backup or restore
runs at a time (``.lock`` in the backup directory, also across containers).
"""
from __future__ import annotations

import fcntl
import hashlib
import io
import json
import logging
import os
import re
import shutil
import tarfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO, Callable, Iterator, Optional

from .postgres import Postgres
from .s3 import S3, NotFound

log = logging.getLogger(__name__)

FORMAT = "od-backup"
FORMAT_VERSION = 1
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
LOCK_FILE = ".lock"
CONTENT_TYPE_PAX = "OD.content_type"
DISK_RESERVE = 1.05  # free space needed = estimated backup size x this factor


class BackupError(RuntimeError):
    pass


class BusyError(BackupError):
    pass


@dataclass
class Config:
    backup_dir: str
    database_url: str
    model_cache_dir: Optional[str] = None
    alembic_versions_dir: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            backup_dir=os.environ.get("BACKUP_DIR", "/backups"),
            database_url=os.environ["DATABASE_URL"],
            model_cache_dir=os.environ.get("MODEL_CACHE_DIR") or None,
            alembic_versions_dir=os.environ.get("ALEMBIC_VERSIONS_DIR") or None,
        )


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_name() -> str:
    return datetime.now(timezone.utc).strftime("backup-%Y%m%d-%H%M%S")


def check_name(name: str) -> str:
    if not NAME_RE.match(name) or name.endswith(".tar"):
        raise BackupError(f"invalid backup name '{name}' (letters, digits, '.', '_', '-')")
    return name


# -- locking & status ------------------------------------------------------------------
@contextmanager
def exclusive(backup_dir: str) -> Iterator[None]:
    os.makedirs(backup_dir, exist_ok=True)
    fd = os.open(os.path.join(backup_dir, LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BusyError("another backup or restore is running") from exc
        yield
    finally:
        os.close(fd)  # releases the lock


def is_busy(backup_dir: str) -> bool:
    try:
        with exclusive(backup_dir):
            return False
    except BusyError:
        return True


class StatusFile:
    """``<name>.json`` next to the tar file; written atomically, progress updates throttled."""

    def __init__(self, backup_dir: str, name: str, initial: Optional[dict] = None):
        self.path = os.path.join(backup_dir, f"{name}.json")
        self.data: dict[str, Any] = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        self.data.update(initial or {})
        self._last = 0.0
        self.write()

    def update(self, force: bool = True, **values: Any) -> None:
        self.data.update(values)
        if force or time.monotonic() - self._last >= 1.0:
            self.write()

    def write(self) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)
        self._last = time.monotonic()


def _paths(backup_dir: str, name: str) -> dict[str, str]:
    return {
        "tar": os.path.join(backup_dir, f"{name}.tar"),
        "partial": os.path.join(backup_dir, f".{name}.tar.partial"),
        "dump": os.path.join(backup_dir, f".{name}.dump.tmp"),
        "status": os.path.join(backup_dir, f"{name}.json"),
    }


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = len(data), time.time(), 0o644
    tar.addfile(info, io.BytesIO(data))


class _Counting(io.RawIOBase):
    """Read-through wrapper that reports the number of bytes read."""

    def __init__(self, stream: BinaryIO, on_bytes: Callable[[int], None]):
        self.stream, self.on_bytes = stream, on_bytes

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.on_bytes(len(data))
        return data


# -- create ------------------------------------------------------------------------------
def create_backup(cfg: Config, s3: S3, pg: Postgres, name: Optional[str] = None, source: str = "cli") -> dict:
    """Write a complete backup. Blocks until done (no timeout); progress goes to ``<name>.json``."""
    name = check_name(name or new_name())
    p = _paths(cfg.backup_dir, name)
    with exclusive(cfg.backup_dir):
        if os.path.exists(p["tar"]):
            raise BackupError(f"backup '{name}' already exists")
        status = StatusFile(cfg.backup_dir, name, {
            "name": name, "file": f"{name}.tar", "status": "running", "phase": "inventory", "source": source,
            "created_at": utcnow(), "started_at": utcnow(), "finished_at": None, "error": None, "warnings": [],
        })
        started = time.monotonic()
        try:
            summary = _write_backup(cfg, s3, pg, name, p, status)
        except BaseException as exc:
            for key in ("partial", "dump"):
                if os.path.exists(p[key]):
                    os.remove(p[key])
            status.update(status="failed", phase=None, finished_at=utcnow(),
                          error=str(exc) or exc.__class__.__name__, duration_s=round(time.monotonic() - started))
            raise
        status.update(status="completed", phase=None, finished_at=utcnow(), size_bytes=os.path.getsize(p["tar"]),
                      warnings=summary["warnings"], duration_s=round(time.monotonic() - started))
        log.info("backup %s completed (%d bytes)", name, status.data["size_bytes"])
        return status.data


def _write_backup(cfg: Config, s3: S3, pg: Postgres, name: str, p: dict[str, str], status: StatusFile) -> dict:
    # 1) inventory: object lists first, so totals for progress and disk check are known
    inventory = {logical: s3.list(logical) for logical in s3.iter_logical()}
    counts = pg.counts()
    bucket_info = {logical: {"bucket": s3.buckets[logical], "objects": len(objs), "bytes": sum(o.size for o in objs)}
                   for logical, objs in inventory.items()}
    total_bytes = sum(b["bytes"] for b in bucket_info.values())
    estimate = total_bytes + pg.size_bytes()
    free = shutil.disk_usage(cfg.backup_dir).free
    if estimate * DISK_RESERVE > free:
        raise BackupError(f"not enough disk space in {cfg.backup_dir}: about {estimate // 2**20} MB needed, "
                          f"{free // 2**20} MB free")
    status.update(contents={**counts, **{f"{k}_objects": v["objects"] for k, v in bucket_info.items()}},
                  progress={"objects_done": 0, "objects_total": sum(len(o) for o in inventory.values()),
                            "bytes_done": 0, "bytes_total": total_bytes},
                  estimated_bytes=estimate)

    # 2) database: consistent snapshot (pg_dump runs in one transaction)
    status.update(phase="database")
    revision = pg.alembic_revision()
    pg.dump(p["dump"])
    sha = hashlib.sha256()
    with open(p["dump"], "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)

    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION, "name": name, "created_at": status.data["created_at"],
        "source": status.data["source"],
        "database": {"alembic_revision": revision, "dump_bytes": os.path.getsize(p["dump"]), "dump_sha256": sha.hexdigest(),
                     "counts": counts},
        "buckets": bucket_info,
    }

    # 3) tar: manifest, dump, all objects, summary
    warnings: list[str] = []
    written = {logical: 0 for logical in inventory}
    progress = status.data["progress"]

    def on_bytes(n: int) -> None:
        progress["bytes_done"] += n
        status.update(force=False, progress=progress)

    with open(p["partial"], "wb") as raw, tarfile.open(fileobj=raw, mode="w|", format=tarfile.PAX_FORMAT) as tar:
        _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=2).encode())
        tar.add(p["dump"], arcname="database.dump")
        os.remove(p["dump"])
        for logical, objects in inventory.items():
            status.update(phase=logical)
            for obj in objects:
                try:
                    src = s3.open(logical, obj.key)
                except NotFound:  # deleted while the backup was running
                    warnings.append(f"{logical}/{obj.key}: deleted during the backup, not included")
                    continue
                info = tarfile.TarInfo(f"s3/{logical}/{obj.key}")
                info.size, info.mtime, info.mode = src.size, src.mtime, 0o644
                if src.content_type:
                    info.pax_headers = {CONTENT_TYPE_PAX: src.content_type}
                try:
                    tar.addfile(info, _Counting(src.body, on_bytes))
                finally:
                    src.body.close()
                written[logical] += 1
                progress["objects_done"] += 1
                status.update(force=False, progress=progress)
        status.update(phase="finalizing")
        summary = {"completed_at": utcnow(), "objects": written, "warnings": warnings}
        _add_bytes(tar, "summary.json", json.dumps(summary, indent=2).encode())
        tar.close()
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(p["partial"], p["tar"])
    return summary


# -- read / verify ---------------------------------------------------------------------
def read_manifest(path: str) -> dict:
    """First member of the tar - cheap, no need to read the whole file."""
    with tarfile.open(path, mode="r|") as tar:
        member = tar.next()
        if member is None or member.name != "manifest.json":
            raise BackupError(f"{os.path.basename(path)} is not a backup of this system (manifest.json missing)")
        manifest = json.load(tar.extractfile(member))
    if manifest.get("format") != FORMAT:
        raise BackupError(f"{os.path.basename(path)} is not a backup of this system")
    if manifest.get("format_version", 0) > FORMAT_VERSION:
        raise BackupError(f"backup format {manifest['format_version']} is newer than this tool supports ({FORMAT_VERSION})")
    return manifest


def verify_backup(path: str) -> dict:
    """Read the whole file once: structure, database checksum, object counts against summary.json."""
    manifest = read_manifest(path)
    seen = {logical: 0 for logical in manifest["buckets"]}
    summary, dump_ok = None, False
    with tarfile.open(path, mode="r|") as tar:
        for member in tar:
            if member.name == "database.dump":
                sha = hashlib.sha256()
                f = tar.extractfile(member)
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    sha.update(chunk)
                if sha.hexdigest() != manifest["database"]["dump_sha256"]:
                    raise BackupError("database dump is corrupt (checksum mismatch)")
                dump_ok = True
            elif member.name.startswith("s3/"):
                seen[member.name.split("/", 2)[1]] += 1
            elif member.name == "summary.json":
                summary = json.load(tar.extractfile(member))
    if not dump_ok:
        raise BackupError("database dump missing")
    if summary is None:
        raise BackupError("backup is incomplete (summary.json missing - file truncated?)")
    if seen != summary["objects"]:
        raise BackupError(f"object count mismatch: file contains {seen}, expected {summary['objects']}")
    return {"manifest": manifest, "summary": summary}


def known_revisions(versions_dir: Optional[str]) -> Optional[set[str]]:
    if not versions_dir or not os.path.isdir(versions_dir):
        return None
    pattern = re.compile(r"""^revision\s*(?::\s*\w+\s*)?=\s*["']([^"']+)["']""", re.M)
    revisions = set()
    for entry in os.listdir(versions_dir):
        if entry.endswith(".py"):
            with open(os.path.join(versions_dir, entry), encoding="utf-8") as f:
                revisions.update(pattern.findall(f.read()))
    return revisions


# -- restore -----------------------------------------------------------------------------
def restore_backup(cfg: Config, s3: S3, pg: Postgres, path: str, force: bool = False, verify: bool = True,
                   echo: Callable[[str], None] = print) -> dict:
    """Replace database and all buckets with the content of the backup.

    Order: verify the file (nothing changed yet) -> restore the dump into a new database ->
    swap it in (old one kept as ``<db>_before_restore``) -> replace bucket contents -> clear the
    API's model cache. API and trainer must be stopped.
    """
    with exclusive(cfg.backup_dir):
        others = pg.other_connections()
        if others and not force:
            raise BackupError(f"{others} other connection(s) to the database - stop api and trainer first "
                              "(docker compose stop api trainer) or use --force")
        if verify:
            echo("checking the backup file ...")
            manifest = verify_backup(path)["manifest"]
        else:
            manifest = read_manifest(path)
        revision = manifest["database"]["alembic_revision"]
        known = known_revisions(cfg.alembic_versions_dir)
        if known is not None and revision and revision not in known and not force:
            raise BackupError(f"backup has database schema '{revision}', which this version does not know "
                              "(backup from a newer version?) - use --force to restore anyway")
        started = time.monotonic()
        result: dict[str, Any] = {"name": manifest["name"], "objects": {}, "warnings": []}
        with tarfile.open(path, mode="r|") as tar:
            tar.next()  # manifest
            member = tar.next()
            if member is None or member.name != "database.dump":
                raise BackupError("unexpected file layout (database.dump must follow manifest.json)")
            echo("restoring the database into a new database ...")
            restored = pg.restore_into_new_database(tar.extractfile(member))
            result["previous_database"] = pg.swap_in(restored)
            echo(f"database replaced (previous one kept as '{result['previous_database']}')")

            for logical in s3.iter_logical():
                removed = s3.empty(logical)
                echo(f"bucket {s3.buckets[logical]}: {removed} existing objects removed")
            total = sum(b["objects"] for b in manifest["buckets"].values())
            done, last = 0, time.monotonic()
            try:
                for member in tar:
                    if not member.name.startswith("s3/"):
                        continue
                    _, logical, key = member.name.split("/", 2)
                    if logical not in s3.buckets:
                        result["warnings"].append(f"unknown bucket '{logical}' in backup, skipped")
                        continue
                    s3.put(logical, key, tar.extractfile(member), member.size, member.pax_headers.get(CONTENT_TYPE_PAX))
                    result["objects"][logical] = result["objects"].get(logical, 0) + 1
                    done += 1
                    if time.monotonic() - last > 5:
                        echo(f"objects restored: {done}/{total}")
                        last = time.monotonic()
            except Exception as exc:
                raise BackupError(f"restoring the objects failed after {done} of {total}: {exc}. The database is already "
                                  "restored - run the restore again to complete it.") from exc
        if cfg.model_cache_dir and os.path.isdir(cfg.model_cache_dir):
            # cached OpenVINO files are keyed by version name; versions may now differ
            for entry in os.listdir(cfg.model_cache_dir):
                target = os.path.join(cfg.model_cache_dir, entry)
                shutil.rmtree(target) if os.path.isdir(target) else os.remove(target)
            echo("model cache of the API cleared")
        result["duration_s"] = round(time.monotonic() - started)
        result["alembic_revision"] = revision
        return result


# -- list / maintenance ------------------------------------------------------------------
def list_backups(backup_dir: str) -> list[dict]:
    """Status files plus tar files without one (e.g. copied in from another system)."""
    if not os.path.isdir(backup_dir):
        return []
    items: dict[str, dict] = {}
    for entry in os.listdir(backup_dir):
        path = os.path.join(backup_dir, entry)
        if entry.endswith(".json") and not entry.startswith("."):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                items[data["name"]] = data
            except (OSError, ValueError, KeyError):
                continue
    for entry in os.listdir(backup_dir):
        name = entry[:-4]
        if entry.endswith(".tar") and not entry.startswith(".") and name not in items:
            path = os.path.join(backup_dir, entry)
            try:
                manifest = read_manifest(path)
                items[name] = {"name": name, "file": entry, "status": "completed", "source": "imported",
                               "created_at": manifest["created_at"], "finished_at": None, "error": None, "warnings": [],
                               "contents": {**manifest["database"]["counts"],
                                            **{f"{k}_objects": v["objects"] for k, v in manifest["buckets"].items()}}}
            except (BackupError, tarfile.TarError, OSError, ValueError, KeyError) as exc:
                items[name] = {"name": name, "file": entry, "status": "invalid", "error": str(exc), "created_at": None}
    for name, item in items.items():
        tar = os.path.join(backup_dir, f"{name}.tar")
        item["file_exists"] = os.path.exists(tar)
        if item["file_exists"]:
            item["size_bytes"] = os.path.getsize(tar)
    return sorted(items.values(), key=lambda i: i.get("created_at") or "", reverse=True)


def mark_interrupted(backup_dir: str, pending: frozenset[str] = frozenset()) -> int:
    """After a crash/restart: running backups (and queued ones whose job is gone) can never finish."""
    if not os.path.isdir(backup_dir) or is_busy(backup_dir):
        return 0
    fixed = 0
    for item in list_backups(backup_dir):
        if item.get("status") == "running" or (item.get("status") == "queued" and item["name"] not in pending):
            p = _paths(backup_dir, item["name"])
            for key in ("partial", "dump"):
                if os.path.exists(p[key]):
                    os.remove(p[key])
            StatusFile(backup_dir, item["name"]).update(status="failed", phase=None, finished_at=utcnow(),
                                                         error="interrupted (backup service was stopped or restarted)")
            fixed += 1
    return fixed
