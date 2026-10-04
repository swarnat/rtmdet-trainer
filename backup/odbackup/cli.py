"""Command line interface of the backup service, e.g. ``docker compose exec backup odbackup list``.

    odbackup create [--name NAME]              write a backup now (blocks until done)
    odbackup list                              backups in BACKUP_DIR
    odbackup verify FILE                       read and check a backup file completely
    odbackup restore FILE [--yes] [--force]    replace database and buckets with the backup
    odbackup worker                            process backups requested in the UI (RQ queue "backup")

FILE is a path or the name of a backup in BACKUP_DIR (``backup-20261004-101500`` or ``….tar``).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .core import BackupError, Config, create_backup, list_backups, mark_interrupted, restore_backup, verify_backup
from .postgres import DatabaseError, Postgres
from .s3 import S3


def _human(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return str(n)


def _resolve(cfg: Config, file: str) -> str:
    if os.path.exists(file):
        return file
    candidate = os.path.join(cfg.backup_dir, file if file.endswith(".tar") else f"{file}.tar")
    if os.path.exists(candidate):
        return candidate
    raise BackupError(f"backup file '{file}' not found (looked in {cfg.backup_dir})")


def cmd_create(cfg: Config, args) -> None:
    result = create_backup(cfg, S3(), Postgres(cfg.database_url), name=args.name, source="cli")
    print(f"backup written: {os.path.join(cfg.backup_dir, result['file'])} ({_human(result['size_bytes'])}, "
          f"{result['duration_s']} s)")
    for w in result["warnings"]:
        print(f"warning: {w}")


def cmd_list(cfg: Config, args) -> None:
    items = list_backups(cfg.backup_dir)
    if not items:
        print(f"no backups in {cfg.backup_dir}")
    for i in items:
        c = i.get("contents") or {}
        print(f"{i['name']:<28} {i.get('status', '?'):<10} {_human(i.get('size_bytes')):>10}  {i.get('created_at') or '':<25} "
              f"{c.get('images', '-')} images, {c.get('annotations', '-')} boxes, {c.get('model_versions', '-')} models"
              + (f"  ERROR: {i['error']}" if i.get("error") else ""))


def cmd_verify(cfg: Config, args) -> None:
    result = verify_backup(_resolve(cfg, args.file))
    m = result["manifest"]
    print(f"OK: {m['name']} from {m['created_at']}, schema {m['database']['alembic_revision']}, "
          f"objects {result['summary']['objects']}")


def cmd_restore(cfg: Config, args) -> None:
    path = _resolve(cfg, args.file)
    if not args.yes:
        print(f"Restoring {path} REPLACES the complete database and all images, datasets and models.\n"
              "Everything created after this backup is lost. API and trainer must be stopped.")
        if input("Type 'restore' to continue: ").strip() != "restore":
            print("aborted")
            sys.exit(1)
    result = restore_backup(cfg, S3(), Postgres(cfg.database_url), path, force=args.force, verify=not args.skip_verify)
    print(f"restore of {result['name']} completed in {result['duration_s']} s: objects {result['objects']}")
    print(f"The previous database is kept as '{result['previous_database']}' (dropped by the next restore). "
          "Start the stack again: docker compose up -d")
    for w in result["warnings"]:
        print(f"warning: {w}")


def cmd_worker(cfg: Config, args) -> None:
    from redis import Redis
    from rq import Queue, Worker

    from .jobs import QUEUE

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    queue = Queue(QUEUE, connection=redis)
    pending = frozenset(j.removeprefix("backup-") for j in queue.job_ids)
    fixed = mark_interrupted(cfg.backup_dir, pending)
    if fixed:
        logging.getLogger(__name__).warning("%d interrupted backup(s) marked as failed", fixed)
    logging.getLogger(__name__).info("backup worker listening on queue '%s', backups in %s", QUEUE, cfg.backup_dir)
    Worker([queue], connection=redis).work(with_scheduler=False, logging_level="INFO")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="odbackup", description="Backup and restore of the object detection stack")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create", help="write a backup now")
    p.add_argument("--name", help="file name without .tar (default: backup-<UTC time>)")
    sub.add_parser("list", help="list backups")
    p = sub.add_parser("verify", help="check a backup file")
    p.add_argument("file")
    p = sub.add_parser("restore", help="replace database and buckets with a backup")
    p.add_argument("file")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--force", action="store_true", help="ignore open database connections / unknown schema version")
    p.add_argument("--skip-verify", action="store_true", help="do not read the file completely before restoring")
    sub.add_parser("worker", help="process backups requested in the UI")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    commands = {"create": cmd_create, "list": cmd_list, "verify": cmd_verify, "restore": cmd_restore, "worker": cmd_worker}
    try:
        commands[args.command](cfg, args)
    except (BackupError, DatabaseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
