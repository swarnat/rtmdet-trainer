"""PostgreSQL access through the native client tools (pg_dump, pg_restore, psql) - no timeouts."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import BinaryIO, Optional
from urllib.parse import unquote, urlparse

MAINTENANCE_DB = "postgres"


class DatabaseError(RuntimeError):
    pass


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class Postgres:
    def __init__(self, database_url: str):
        # SQLAlchemy URL, e.g. postgresql+psycopg://user:password@postgres:5432/object_detection
        url = urlparse(database_url.split("+", 1)[0] + "://" + database_url.split("://", 1)[1])
        if not url.path.strip("/"):
            raise DatabaseError("DATABASE_URL contains no database name")
        self.dbname = unquote(url.path.strip("/"))
        self.env = {
            **os.environ,
            "PGHOST": url.hostname or "localhost",
            "PGPORT": str(url.port or 5432),
            "PGUSER": unquote(url.username or ""),
            "PGPASSWORD": unquote(url.password or ""),
            "PGAPPNAME": "od-backup",
        }

    # -- helpers ---------------------------------------------------------------------
    def _run(self, args: list[str]) -> str:
        res = subprocess.run(args, env=self.env, capture_output=True, text=True)
        if res.returncode != 0:
            raise DatabaseError(f"{args[0]} failed: {res.stderr.strip() or res.stdout.strip()}")
        return res.stdout

    def query(self, sql: str, dbname: Optional[str] = None) -> list[list[str]]:
        out = self._run(["psql", "-X", "-A", "-t", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-d", dbname or self.dbname, "-c", sql])
        return [line.split("\t") for line in out.splitlines() if line]

    def scalar(self, sql: str, dbname: Optional[str] = None) -> Optional[str]:
        rows = self.query(sql, dbname)
        return rows[0][0] if rows else None

    # -- information ---------------------------------------------------------------
    def size_bytes(self) -> int:
        return int(self.scalar("SELECT pg_database_size(current_database())") or 0)

    def alembic_revision(self) -> Optional[str]:
        if self.scalar("SELECT to_regclass('public.alembic_version') IS NOT NULL") != "t":
            return None
        return self.scalar("SELECT version_num FROM alembic_version")

    def counts(self) -> dict[str, int]:
        """Row counts for the backup summary (tables missing in older schemas count as 0)."""
        queries = {
            "images": "SELECT count(*) FROM images",
            "images_labeled": "SELECT count(*) FROM images WHERE annotation_status = 'labeled'",
            "annotations": "SELECT count(*) FROM annotations WHERE type = 'positive'",
            "hard_negatives": "SELECT count(*) FROM annotations WHERE type = 'hard_negative'",
            "classes": "SELECT count(*) FROM detection_classes",
            "model_versions": "SELECT count(*) FROM model_versions",
            "training_runs": "SELECT count(*) FROM training_runs",
            "settings": "SELECT count(*) FROM settings",
        }
        result = {}
        for key, sql in queries.items():
            try:
                result[key] = int(self.scalar(sql) or 0)
            except DatabaseError:
                result[key] = 0
        return result

    def other_connections(self) -> int:
        """Client connections to the database other than this tool's own."""
        return int(self.scalar(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
        ) or 0)

    # -- dump / restore ------------------------------------------------------------
    def dump(self, path: str) -> None:
        """Consistent snapshot in pg_dump's compressed custom format."""
        self._run(["pg_dump", "--format=custom", "--compress=6", "--no-owner", "--no-privileges",
                   "--file", path, "--dbname", self.dbname])

    def restore_into_new_database(self, stream: BinaryIO) -> str:
        """Restore a custom-format dump (read sequentially from ``stream``) into ``<db>_restore``.

        The live database is not touched; a failure leaves everything as it was.
        """
        tmp = f"{self.dbname}_restore"
        self.drop_database(tmp)
        self.query(f"CREATE DATABASE {_ident(tmp)}", MAINTENANCE_DB)
        proc = subprocess.Popen(
            ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "--dbname", tmp],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env,
        )
        try:
            shutil.copyfileobj(stream, proc.stdin, 1024 * 1024)
            proc.stdin.close()
        except BrokenPipeError:
            pass  # pg_restore stopped early: its exit code and stderr explain why
        stderr = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            self.drop_database(tmp)
            raise DatabaseError(f"pg_restore failed: {stderr.strip()}")
        return tmp

    def swap_in(self, restored: str) -> str:
        """Replace the live database by ``restored``; the previous one is kept as ``<db>_before_restore``."""
        old = f"{self.dbname}_before_restore"
        self.drop_database(old)
        self.query(f"ALTER DATABASE {_ident(self.dbname)} RENAME TO {_ident(old)}", MAINTENANCE_DB)
        try:
            self.query(f"ALTER DATABASE {_ident(restored)} RENAME TO {_ident(self.dbname)}", MAINTENANCE_DB)
        except DatabaseError:
            self.query(f"ALTER DATABASE {_ident(old)} RENAME TO {_ident(self.dbname)}", MAINTENANCE_DB)
            raise
        return old

    def drop_database(self, name: str) -> None:
        self.query(f"DROP DATABASE IF EXISTS {_ident(name)} WITH (FORCE)", MAINTENANCE_DB)
