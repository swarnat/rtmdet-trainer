"""Redis/RQ job queue used to hand training jobs to the trainer service."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Optional

from redis import Redis
from rq import Queue

from .config import get_settings

log = logging.getLogger(__name__)

TRAIN_JOB = "trainer.worker.run_training_job"
# written by the trainer healthcheck every 30 s (trainer/trainer/gpu.py), expires when it stops reporting
GPU_STATUS_KEY = "trainer:gpu"
BOOTSTRAP_JOB = "trainer.worker.run_bootstrap_job"
BENCHMARK_JOB = "trainer.worker.run_benchmark_job"
CANDIDATE_JOB = "trainer.worker.run_candidate_search_job"


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


def enqueue_bootstrap(force: bool = False, base_id: str = "rtmdet-s-coco") -> str:
    job = get_queue().enqueue(BOOTSTRAP_JOB, force, base_id, job_timeout=3600, result_ttl=86400, failure_ttl=7 * 86400)
    return job.id


def enqueue_benchmark(benchmark_id: int) -> str:
    # no timeout, like trainings: RQ measures it with the wall clock, and WSL2 clock jumps killed a running benchmark
    job = get_queue().enqueue(BENCHMARK_JOB, benchmark_id, job_timeout=-1, result_ttl=86400, failure_ttl=7 * 86400,
                              job_id=f"benchmark-{benchmark_id}")
    return job.id


def enqueue_candidate_search(search_id: int) -> str:
    # no timeout: a search over many images takes as long as it takes (see enqueue_benchmark)
    job = get_queue().enqueue(CANDIDATE_JOB, search_id, job_timeout=-1, result_ttl=86400, failure_ttl=7 * 86400,
                              job_id=f"candidate-search-{search_id}")
    return job.id


def trainer_gpu_status() -> Optional[dict]:
    """Last GPU probe of the trainer (``available``, ``devices``, ``error``, ``checked_at``); None = unknown."""
    try:
        raw = get_redis().get(GPU_STATUS_KEY)
    except Exception:
        log.warning("could not read the trainer GPU status", exc_info=True)
        return None
    return json.loads(raw) if raw else None
