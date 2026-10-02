"""Redis/RQ job queue used to hand training jobs to the trainer service."""
from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue

from .config import get_settings

TRAIN_JOB = "trainer.worker.run_training_job"
BOOTSTRAP_JOB = "trainer.worker.run_bootstrap_job"


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


@lru_cache
def get_queue() -> Queue:
    return Queue(get_settings().training_queue, connection=get_redis())


def enqueue_training(run_id: int) -> str:
    # The function is referenced by name; it only exists in the trainer image.
    job = get_queue().enqueue(TRAIN_JOB, run_id, job_timeout=-1, result_ttl=86400, failure_ttl=7 * 86400,
                              job_id=f"training-run-{run_id}")
    return job.id


def enqueue_bootstrap(force: bool = False) -> str:
    job = get_queue().enqueue(BOOTSTRAP_JOB, force, job_timeout=3600, result_ttl=86400, failure_ttl=7 * 86400)
    return job.id
