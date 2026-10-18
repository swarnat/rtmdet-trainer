"""Deliberately simple storage: image files in a directory, one SQLite table, the pushed configuration as JSON.

Everything lives below DATA_DIR (Docker volume)::

    config.json                pushed by the training system (classes, inference server, confidence)
    client.db                  table ``images`` (metadata, annotations and detections as JSON)
    images/<sha256>.<ext>      original files
    thumbnails/<sha256>.jpg
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from odcore.images import DecodedImage, make_thumbnail

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT,
    source_url TEXT,
    content_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    -- open | annotated (annotated with an empty list = negative image)
    status TEXT NOT NULL DEFAULT 'open',
    annotations TEXT NOT NULL DEFAULT '[]',
    -- latest check against the inference server: {"model_version", "input_width", "input_height", "confidence",
    -- "detections": [{"class", "confidence", "bbox": {x1, y1, x2, y2}}], "created_at"}; NULL = not checked
    detection TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    annotated_at TEXT
)
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["annotations"] = json.loads(out["annotations"])
    out["detection"] = json.loads(out["detection"]) if out["detection"] else None
    return out


class Store:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.images_dir = os.path.join(data_dir, "images")
        self.thumbs_dir = os.path.join(data_dir, "thumbnails")
        self.db_path = os.path.join(data_dir, "client.db")
        self.config_path = os.path.join(data_dir, "config.json")
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.thumbs_dir, exist_ok=True)
        self._lock = threading.Lock()  # one writer at a time (SQLite + files)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:  # commit or roll back
                yield db
        finally:
            db.close()

    # -- configuration ---------------------------------------------------------------
    def get_config(self) -> Optional[dict[str, Any]]:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def set_config(self, config: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.data_dir, prefix=".config-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.config_path)  # atomic: never a half-written file

    # -- images ------------------------------------------------------------------------
    def file_path(self, image: dict[str, Any]) -> str:
        return os.path.join(self.images_dir, image["sha256"] + image["extension"])

    def thumbnail_path(self, image: dict[str, Any]) -> str:
        return os.path.join(self.thumbs_dir, image["sha256"] + ".jpg")

    def add(self, decoded: DecodedImage, filename: Optional[str], source_url: Optional[str]) -> tuple[dict[str, Any], bool]:
        """Store a validated image. Returns (image, created); the same content again is not stored twice."""
        with self._lock:
            existing = self.get_by_sha(decoded.sha256)
            if existing is not None:
                return existing, False
            image = {"sha256": decoded.sha256, "extension": decoded.extension}
            with open(self.file_path(image), "wb") as f:
                f.write(decoded.data)
            with open(self.thumbnail_path(image), "wb") as f:
                f.write(make_thumbnail(decoded.image))
            now = utcnow()
            with self._db() as db:
                cur = db.execute(
                    "INSERT INTO images (sha256, filename, source_url, content_type, extension, size_bytes, width, height, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (decoded.sha256, (filename or "")[:512] or None, source_url, decoded.content_type, decoded.extension,
                     len(decoded.data), decoded.width, decoded.height, now, now),
                )
                image_id = cur.lastrowid
        return self.get(image_id), True

    def get(self, image_id: int) -> Optional[dict[str, Any]]:
        with self._db() as db:
            row = db.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        return _row(row) if row else None

    def get_by_sha(self, sha256: str) -> Optional[dict[str, Any]]:
        with self._db() as db:
            row = db.execute("SELECT * FROM images WHERE sha256 = ?", (sha256,)).fetchone()
        return _row(row) if row else None

    def list(self, status: Optional[str] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
        query, args = "SELECT * FROM images", []
        if status:
            query += " WHERE status = ?"
            args.append(status)
        query += " ORDER BY id"
        if limit is not None:
            query += " LIMIT ?"
            args.append(limit)
        with self._db() as db:
            return [_row(r) for r in db.execute(query, args).fetchall()]

    def counts(self) -> dict[str, int]:
        with self._db() as db:
            rows = db.execute("SELECT status, COUNT(*) FROM images GROUP BY status").fetchall()
        counts = {"open": 0, "annotated": 0}
        counts.update({status: n for status, n in rows})
        counts["total"] = counts["open"] + counts["annotated"]
        return counts

    def save_annotations(self, image_id: int, annotations: list[dict[str, Any]], mark_annotated: bool) -> dict[str, Any]:
        now = utcnow()
        with self._lock, self._db() as db:
            if mark_annotated:
                db.execute("UPDATE images SET annotations = ?, status = 'annotated', annotated_at = ?, updated_at = ? WHERE id = ?",
                           (json.dumps(annotations), now, now, image_id))
            else:
                db.execute("UPDATE images SET annotations = ?, updated_at = ? WHERE id = ?", (json.dumps(annotations), now, image_id))
        return self.get(image_id)

    def set_status_open(self, image_id: int) -> dict[str, Any]:
        with self._lock, self._db() as db:
            db.execute("UPDATE images SET status = 'open', annotated_at = NULL, updated_at = ? WHERE id = ?", (utcnow(), image_id))
        return self.get(image_id)

    def save_detection(self, image_id: int, detection: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._db() as db:
            db.execute("UPDATE images SET detection = ?, updated_at = ? WHERE id = ?", (json.dumps(detection), utcnow(), image_id))
        return self.get(image_id)

    def delete(self, image_id: int) -> bool:
        with self._lock:
            image = self.get(image_id)
            if image is None:
                return False
            with self._db() as db:
                db.execute("DELETE FROM images WHERE id = ?", (image_id,))
            for path in (self.file_path(image), self.thumbnail_path(image)):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
        return True
