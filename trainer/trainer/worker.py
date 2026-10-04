"""Training worker: consumes jobs from the Redis queue (RQ).

Start-up sequence:
1. wait for PostgreSQL/Redis/S3 and the DB schema (migrated by the API)
2. mark runs left in 'running' by a crashed/restarted worker as failed
3. release snapshots no longer needed, convert old snapshots with image copies (``odcore.snapshots``)
4. optionally import the COCO bootstrap model if no model exists yet
5. process jobs one at a time (GPU training must not run concurrently)

Every job runs in a fresh subprocess (see ``trainer.run_job``); the worker
process itself never imports torch/CUDA.
"""
from __future__ import annotations

import ctypes
import logging
import signal
import subprocess
import sys
import time

from redis import Redis
from rq import Queue, Worker
from sqlalchemy import inspect, select

from odcore.db import ModelVersion, TrainingRun, TrainingStatus, utcnow
from odcore.snapshots import convert_legacy_snapshots, release_snapshot, release_unneeded_snapshots

from .config import get_settings
from .db import session_factory, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
log = logging.getLogger("trainer.worker")


# -- job entry points (referenced by name from the API) ------------------------
def _set_parent_death_signal() -> None:
    """Child gets SIGTERM if the RQ work horse dies (e.g. job cancelled via stop command)."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:  # pragma: no cover - non-glibc systems
        pass


def _run_subprocess(*args: str) -> None:
    cmd = [sys.executable, "-m", "trainer.run_job", *args]
    log.info("running %s", " ".join(cmd))
    proc = subprocess.run(cmd, preexec_fn=_set_parent_death_signal, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"job process {' '.join(args)} exited with code {proc.returncode}")


def run_training_job(run_id: int) -> None:
    # forked work horse: never reuse the parent's pooled DB connections
    session_factory().kw["bind"].dispose(close=False)
    sweep_snapshots()  # e.g. runs cancelled while their snapshot was being created
    try:
        _run_subprocess("train", str(run_id))
    finally:
        finish_training_run(run_id)


def finish_training_run(run_id: int) -> None:
    """After the training process ended in any way: record a missing failure, release unneeded snapshots."""
    with session_factory()() as session:
        run = session.get(TrainingRun, run_id)
        # The process may have been killed (OOM etc.) before it could record the failure.
        if run is not None and run.status == TrainingStatus.running:
            run.status = TrainingStatus.failed
            run.error = run.error or "training process terminated unexpectedly (see trainer logs)"
            run.finished_at = utcnow()
            session.commit()
        if run is not None and run.status == TrainingStatus.failed:
            # a failed run produces no model: its snapshot (image links, files) is not needed
            release_snapshot(session, storage(), run_id)


class TrainerWorker(Worker):
    """RQ worker that also cleans up when the work horse itself was killed (job stopped via
    "Abbrechen", OOM): then the ``finally`` block of ``run_training_job`` never ran."""

    def monitor_work_horse(self, job, queue):
        try:
            super().monitor_work_horse(job, queue)
        finally:
            if job.func_name == "trainer.worker.run_training_job" and job.args:
                try:
                    finish_training_run(int(job.args[0]))
                except Exception:
                    log.exception("clean-up after training job %s failed", job.id)


def run_bootstrap_job(force: bool = False, base_id: str = "rtmdet-s-coco") -> None:
    _run_subprocess("bootstrap", "--base", base_id, *(["--force"] if force else []))


# -- start-up ---------------------------------------------------------------------
def wait_for_dependencies(timeout: float = 300) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            with session_factory()() as session:
                if not inspect(session.get_bind()).has_table("snapshot_images"):
                    raise RuntimeError("database schema not migrated yet")
            Redis.from_url(get_settings().redis_url).ping()
            storage().check_buckets()
            return
        except Exception as exc:
            if time.time() > deadline:
                raise
            log.info("waiting for dependencies: %s", exc)
            time.sleep(3)


def fail_stale_runs() -> None:
    with session_factory()() as session:
        stale = session.execute(select(TrainingRun).where(TrainingRun.status == TrainingStatus.running)).scalars().all()
        for run in stale:
            log.warning("marking training run %s as failed (worker restarted during training)", run.id)
            run.status = TrainingStatus.failed
            run.error = "worker restarted while the training was running"
            run.finished_at = utcnow()
        session.commit()


def sweep_snapshots() -> None:
    """Release snapshots of failed runs and of deleted models; purge images no snapshot needs."""
    try:
        with session_factory()() as session:
            released = release_unneeded_snapshots(session, storage())
            if released:
                log.info("released %d unneeded dataset snapshot(s)", released)
    except Exception:
        log.exception("snapshot sweep failed")


def convert_snapshots() -> None:
    try:
        with session_factory()() as session:
            convert_legacy_snapshots(session, storage())
    except Exception:
        log.exception("conversion of old dataset snapshots failed (retried on next start)")


def maybe_bootstrap() -> None:
    if not get_settings().bootstrap_on_start:
        return
    with session_factory()() as session:
        if session.execute(select(ModelVersion.id)).first() is not None:
            return
    log.info("no model versions yet: importing COCO-pretrained RTMDet-S as initial model")
    try:
        run_bootstrap_job()
    except Exception:
        log.exception("bootstrap failed; it can be retried from the Models page")


def main() -> None:
    settings = get_settings()
    wait_for_dependencies()
    fail_stale_runs()
    sweep_snapshots()
    convert_snapshots()
    maybe_bootstrap()
    redis = Redis.from_url(settings.redis_url)
    queue = Queue(settings.queue, connection=redis)
    log.info("listening on queue '%s'", settings.queue)
    TrainerWorker([queue], connection=redis, name=None).work(with_scheduler=False, logging_level="INFO")


if __name__ == "__main__":
    main()
