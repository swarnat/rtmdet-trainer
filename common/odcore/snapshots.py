"""Dataset snapshots reference images instead of copying them - with a link count like ``nlink``.

* ``snapshot_images`` holds one row per (training run, image): the "directory entries".
* ``images.snapshot_refs`` is the link count; it changes in the same transaction as the links.
* A training run links its images when its snapshot is created (``link_images``) and releases
  them when the snapshot is no longer needed (``release_snapshot``): failed/cancelled run or
  deleted model. Releasing also removes ``s3://<datasets>/<run>/`` (annotations, manifest,
  hard-negative crops).
* Deleting an image with links only hides it (``deleted_at``); its file stays until the last
  link is released, then ``purge_deleted_images`` removes row and files.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

from sqlalchemy import case, delete, exists, insert, select, update
from sqlalchemy.orm import Session

from .db import Image, SnapshotImage, TrainingRun, TrainingStatus
from .storage import ObjectStorage

log = logging.getLogger(__name__)


def snapshot_prefix(run_id: int) -> str:
    """Location of a run's snapshot inside the datasets bucket."""
    return f"{run_id}/"


def link_images(session: Session, run_id: int, image_ids: Iterable[int]) -> int:
    """Add the run's links and increment the link counts (caller commits)."""
    ids = sorted(set(image_ids))
    if not ids:
        return 0
    session.execute(insert(SnapshotImage), [{"training_run_id": run_id, "image_id": i} for i in ids])
    session.execute(update(Image).where(Image.id.in_(ids)).values(snapshot_refs=Image.snapshot_refs + 1))
    return len(ids)


def release_snapshot(session: Session, storage: ObjectStorage, run_id: int) -> int:
    """Drop a run's snapshot: links, link counts, files in the datasets bucket, unreferenced deleted images.

    Idempotent and safe against concurrent calls (row lock on the run; only links that were
    actually removed are decremented). Returns the number of released links.
    """
    run = session.get(TrainingRun, run_id, with_for_update=True)
    released = list(session.execute(
        delete(SnapshotImage).where(SnapshotImage.training_run_id == run_id).returning(SnapshotImage.image_id)
    ).scalars())
    if released:
        session.execute(
            update(Image).where(Image.id.in_(released))
            .values(snapshot_refs=case((Image.snapshot_refs > 0, Image.snapshot_refs - 1), else_=0))
        )
    had_snapshot = run is not None and run.dataset_snapshot is not None
    if had_snapshot:
        run.dataset_snapshot = None
    session.commit()
    if released or had_snapshot:
        try:
            removed = storage.delete_prefix(storage.settings.bucket_datasets, snapshot_prefix(run_id))
            log.info("released snapshot of training run %s (%d image links, %d files)", run_id, len(released), removed)
        except Exception:
            log.exception("snapshot files of training run %s could not be removed", run_id)
    if released:
        purge_deleted_images(session, storage, released)
    return len(released)


def purge_deleted_images(session: Session, storage: ObjectStorage, image_ids: Optional[list[int]] = None) -> int:
    """Finally delete hidden images that no snapshot references any more (rows and files)."""
    stmt = select(Image).where(
        Image.deleted_at.is_not(None),
        Image.snapshot_refs <= 0,
        ~exists().where(SnapshotImage.image_id == Image.id),
    )
    if image_ids is not None:
        stmt = stmt.where(Image.id.in_(image_ids))
    images = list(session.execute(stmt).scalars())
    keys = [k for img in images for k in (img.s3_object_key, img.thumbnail_key) if k]
    for img in images:
        session.delete(img)
    session.commit()
    for key in keys:
        try:
            storage.delete(storage.settings.bucket_images, key)
        except Exception:
            log.exception("could not delete s3 object %s", key)
    if images:
        log.info("purged %d deleted image(s) no longer used by any snapshot", len(images))
    return len(images)


def needs_snapshot(run: TrainingRun) -> bool:
    """Snapshots are kept for queued/running runs and for completed runs whose model still exists."""
    if run.status in (TrainingStatus.queued, TrainingStatus.running):
        return True
    return run.status == TrainingStatus.completed and run.model_version_id is not None


def release_unneeded_snapshots(session: Session, storage: ObjectStorage) -> int:
    """Sweep: snapshots of failed/cancelled runs and of runs whose model was deleted."""
    candidates = session.execute(
        select(TrainingRun).where(
            TrainingRun.dataset_snapshot.is_not(None)
            | exists().where(SnapshotImage.training_run_id == TrainingRun.id)
        )
    ).scalars().all()
    count = 0
    for run in candidates:
        if not needs_snapshot(run):
            release_snapshot(session, storage, run.id)
            count += 1
    return count


def convert_legacy_snapshots(session: Session, storage: ObjectStorage) -> dict[str, int]:
    """One-time conversion of snapshots that still contain image copies (created before links existed).

    Idempotent: links are created only for runs without links; copies (``<run>/images/`` except
    hard-negative crops ``hn_*``) are removed afterwards. Copies of images that no longer exist in
    the image library are kept (they are the only remaining file).
    """
    stats = {"linked_runs": 0, "links": 0, "copies_removed": 0, "copies_kept": 0}
    bucket = storage.settings.bucket_datasets
    runs = session.execute(
        select(TrainingRun).where(TrainingRun.dataset_snapshot.is_not(None)).order_by(TrainingRun.id)
    ).scalars().all()
    for run in runs:
        if not needs_snapshot(run) or run.status != TrainingStatus.completed:
            continue
        prefix = snapshot_prefix(run.id)
        has_links = session.scalar(select(exists().where(SnapshotImage.training_run_id == run.id)))
        if not has_links:
            try:
                manifest = json.loads(storage.get_bytes(bucket, f"{prefix}manifest.json"))
            except Exception:
                log.warning("snapshot of training run %s has no readable manifest, not converted", run.id)
                continue
            by_sha = dict(session.execute(
                select(Image.sha256, Image.id).where(Image.sha256.in_([i["sha256"] for i in manifest["images"]]))
            ).all())
            stats["links"] += link_images(session, run.id, by_sha.values())
            session.commit()
            stats["linked_runs"] += 1
        linked_shas = set(session.execute(
            select(Image.sha256).join(SnapshotImage, SnapshotImage.image_id == Image.id)
            .where(SnapshotImage.training_run_id == run.id)
        ).scalars())
        for key in list(storage.list_keys(bucket, f"{prefix}images/")):
            name = key.rsplit("/", 1)[-1]
            if name.startswith("hn_"):
                continue  # hard-negative crops are derived per run and stay
            if name.split(".", 1)[0] in linked_shas:
                storage.delete(bucket, key)
                stats["copies_removed"] += 1
            else:
                stats["copies_kept"] += 1
    if stats["linked_runs"] or stats["copies_removed"]:
        log.info("converted legacy dataset snapshots: %s", stats)
    return stats
