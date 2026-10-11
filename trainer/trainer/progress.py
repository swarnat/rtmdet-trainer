"""Streams training logs and progress of a run into PostgreSQL for the UI."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy import update

from odcore.db import TrainingRun

from .db import session_factory

MAX_LOG_CHARS = 300_000  # tail kept in the DB; the full log goes to S3


class RunReporter:
    def __init__(self, run_id: int, log_file: str, flush_interval: float = 3.0):
        self.run_id = run_id
        self.log_file = log_file
        self.flush_interval = flush_interval
        self._buffer: list[str] = []
        self._tail = ""
        self._progress: dict[str, Any] = {}
        self._progress_dirty = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._file = open(log_file, "a", encoding="utf-8")
        self._thread = threading.Thread(target=self._loop, name=f"reporter-{run_id}", daemon=True)
        self._thread.start()

    # -- logging --------------------------------------------------------------
    def write(self, line: str) -> None:
        with self._lock:
            self._buffer.append(line if line.endswith("\n") else line + "\n")

    def handler(self) -> logging.Handler:
        reporter = self

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    reporter.write(self.format(record))
                except Exception:  # pragma: no cover
                    self.handleError(record)

        h = _Handler(level=logging.INFO)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
        return h

    # -- progress -------------------------------------------------------------
    def progress(self, **values: Any) -> None:
        with self._lock:
            self._progress.update(values)
            self._progress_dirty = True

    def get_progress(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._progress)

    # -- flushing -------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.wait(self.flush_interval):
            self.flush()

    def flush(self) -> None:
        with self._lock:
            lines, self._buffer = self._buffer, []
            progress = dict(self._progress) if self._progress_dirty else None
            self._progress_dirty = False
        if not lines and progress is None:
            return
        if lines:
            chunk = "".join(lines)
            self._file.write(chunk)
            self._file.flush()
            self._tail = (self._tail + chunk)[-MAX_LOG_CHARS:]
        values: dict[str, Any] = {}
        if lines:
            values["log"] = self._tail
        if progress is not None:
            values["progress_json"] = progress
        try:
            with session_factory()() as session:
                session.execute(update(TrainingRun).where(TrainingRun.id == self.run_id).values(**values))
                session.commit()
        except Exception:  # DB hiccups must not kill the training
            logging.getLogger(__name__).warning("could not write progress for run %s", self.run_id, exc_info=True)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        self.flush()
        self._file.close()


class ProgressHookFactory:
    """Creates an mmengine hook that reports iteration/epoch progress."""

    @staticmethod
    def create(reporter: RunReporter, phase_offset: float = 0.0, phase_weight: float = 1.0):
        from mmengine.hooks import Hook

        class DbProgressHook(Hook):
            priority = "VERY_LOW"

            def __init__(self) -> None:
                self._t0 = time.time()
                self._last = 0.0
                self.val_history: list[dict] = []

            def after_train_iter(self, runner, batch_idx, data_batch=None, outputs=None) -> None:
                now = time.time()
                if now - self._last < 2.0 and runner.iter + 1 < runner.max_iters:
                    return
                self._last = now
                done = (runner.iter + 1) / max(1, runner.max_iters)
                elapsed = now - self._t0
                eta = elapsed / done * (1 - done) if done > 0 else None
                loss = None
                if outputs and "loss" in outputs:
                    loss = float(outputs["loss"])
                reporter.progress(
                    phase="training",
                    epoch=runner.epoch + 1,
                    max_epochs=runner.max_epochs,
                    iter=runner.iter + 1,
                    max_iters=runner.max_iters,
                    loss=loss,
                    lr=float(runner.optim_wrapper.get_lr()["lr"][0]),
                    percent=round(100 * (phase_offset + phase_weight * done), 1),
                    eta_seconds=round(eta) if eta is not None else None,
                )

            def after_val_epoch(self, runner, metrics=None) -> None:
                if not metrics:
                    return
                entry = {"epoch": runner.epoch}
                for key in ("coco/bbox_mAP", "coco/bbox_mAP_50", "coco/bbox_mAP_s"):
                    if key in metrics:
                        entry[key.split("/")[-1]] = float(metrics[key])
                # detail/<class|size>/<name>/<mAP50|mAP50-95> (trainer.rtmdet.metric)
                for key, value in metrics.items():
                    parts = key.split("/")
                    if len(parts) == 5 and parts[1] == "detail":
                        group = "per_class" if parts[2] == "class" else "per_size"
                        entry.setdefault(group, {}).setdefault(parts[3], {})[parts[4]] = float(value)
                self.val_history.append(entry)
                reporter.progress(val_history=list(self.val_history))

        return DbProgressHook()
