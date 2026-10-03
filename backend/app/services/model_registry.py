"""Resolves model references, fetches OpenVINO IR from S3 and caches compiled models.

Compiled models are cached per (model version, input resolution) with a static
input shape. Model versions are immutable, so cached files never go stale.
Switching the production model only changes a DB row; the next request picks
up the new model without restarting anything.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from odcore.db import ModelStatus, ModelVersion
from odcore.openvino_detector import OpenVinoDetector
from odcore.storage import ObjectStorage

log = logging.getLogger(__name__)


class ModelNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ModelRef:
    version: str
    status: str
    openvino_key: str
    class_names: tuple[str, ...]
    default_width: int
    default_height: int


def resolve_model(session: Session, reference: str | None) -> ModelRef:
    """``None``/'production' -> production model, 'candidate' -> newest candidate,
    otherwise an explicit version such as 'model-0003'."""
    ref = (reference or "production").strip()
    if ref == "production":
        stmt = select(ModelVersion).where(ModelVersion.status == ModelStatus.production)
        not_found = "no production model is active yet (activate a model version first)"
    elif ref == "candidate":
        stmt = (
            select(ModelVersion)
            .where(ModelVersion.status == ModelStatus.candidate)
            .order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc())
            .limit(1)
        )
        not_found = "no candidate model exists"
    else:
        stmt = select(ModelVersion).where(ModelVersion.version == ref)
        not_found = f"model version '{ref}' not found"
    mv = session.execute(stmt).scalars().first()
    if mv is None:
        raise ModelNotFoundError(not_found)
    return ModelRef(
        version=mv.version,
        status=mv.status.value,
        openvino_key=mv.openvino_key,
        class_names=tuple(mv.class_names),
        default_width=mv.input_width,
        default_height=mv.input_height,
    )


class ModelRegistry:
    def __init__(self, storage: ObjectStorage, cache_dir: str, device: str = "CPU", max_compiled: int = 6):
        import openvino as ov

        self.storage = storage
        self.cache_dir = cache_dir
        self.device = device
        self.max_compiled = max_compiled
        self.core = ov.Core()
        os.makedirs(os.path.join(cache_dir, "ov-cache"), exist_ok=True)
        # Let OpenVINO cache compiled blobs on disk as well (faster restarts)
        try:
            self.core.set_property({"CACHE_DIR": os.path.join(cache_dir, "ov-cache")})
        except Exception:  # pragma: no cover - device without caching support
            log.warning("OpenVINO model caching not supported on %s", device)
        self._compiled: OrderedDict[tuple[str, int, int], OpenVinoDetector] = OrderedDict()
        self._lock = threading.Lock()
        self._key_locks: dict[tuple[str, int, int], threading.Lock] = {}

    # -- files ---------------------------------------------------------------
    def local_ir_path(self, ref: ModelRef) -> str:
        """Download ``model.xml``/``model.bin`` once per (immutable) version."""
        target_dir = os.path.join(self.cache_dir, ref.version)
        xml_path = os.path.join(target_dir, "model.xml")
        if os.path.exists(xml_path) and os.path.exists(os.path.join(target_dir, "model.bin")):
            return xml_path
        bucket = self.storage.settings.bucket_models
        bin_key = ref.openvino_key[: -len(".xml")] + ".bin"
        tmp_dir = tempfile.mkdtemp(prefix=f".{ref.version}-", dir=self.cache_dir)
        try:
            log.info("downloading OpenVINO model %s from s3://%s/%s", ref.version, bucket, ref.openvino_key)
            self.storage.download_file(bucket, ref.openvino_key, os.path.join(tmp_dir, "model.xml"))
            self.storage.download_file(bucket, bin_key, os.path.join(tmp_dir, "model.bin"))
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
            os.replace(tmp_dir, target_dir)
        finally:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
        return xml_path

    # -- compiled models -------------------------------------------------------
    def get_detector(self, ref: ModelRef, width: int, height: int) -> OpenVinoDetector:
        key = (ref.version, width, height)
        with self._lock:
            det = self._compiled.get(key)
            if det is not None:
                self._compiled.move_to_end(key)
                return det
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:  # compile each (version, size) only once, even under concurrency
            with self._lock:
                det = self._compiled.get(key)
                if det is not None:
                    return det
            xml_path = self.local_ir_path(ref)
            log.info("compiling %s for static input [1, 3, %d, %d] on %s", ref.version, height, width, self.device)
            det = OpenVinoDetector(self.core, xml_path, width, height, device=self.device)
            with self._lock:
                self._compiled[key] = det
                while len(self._compiled) > self.max_compiled:
                    evicted, _ = self._compiled.popitem(last=False)
                    log.info("evicting compiled model %s", evicted)
            return det

    def forget(self, version: str) -> None:
        """Drop compiled models and downloaded files of a deleted version."""
        with self._lock:
            for key in [k for k in self._compiled if k[0] == version]:
                del self._compiled[key]
        shutil.rmtree(os.path.join(self.cache_dir, version), ignore_errors=True)

    def loaded(self) -> list[dict]:
        with self._lock:
            return [{"version": v, "input_width": w, "input_height": h} for (v, w, h) in self._compiled]


_registry: ModelRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                from app.core.config import get_settings
                from app.core.s3 import get_storage

                s = get_settings()
                _registry = ModelRegistry(get_storage(), s.model_cache_dir, s.openvino_device, s.compiled_model_cache_size)
    return _registry
