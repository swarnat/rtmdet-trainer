"""The single active model: installed via upload, persisted on a volume, swapped atomically.

Layout of ``MODEL_DIR``::

    active.json                      {"dir": "model-0004-20261003T201500Z"}
    model-0004-20261003T201500Z/     model.xml, model.bin, manifest.json

A new model is only activated after it was compiled and passed a test inference;
until then (and if anything fails) the previous model keeps serving requests.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO, Optional

import numpy as np
from pydantic import BaseModel, Field

from odcore.geometry import validate_input_size
from odcore.openvino_detector import DetectionResult, OpenVinoDetector

log = logging.getLogger(__name__)

ACTIVE_FILE = "active.json"


class ModelManifest(BaseModel):
    version: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$", examples=["model-0004"])
    class_names: list[str] = Field(min_length=1, description="class of each score column, in model order")
    input_width: int = Field(gt=0, examples=[1536])
    input_height: int = Field(gt=0, examples=[864])
    nms_iou_threshold: float = Field(0.6, gt=0, le=1)
    architecture: Optional[str] = None
    metrics: Optional[dict[str, Any]] = Field(None, description="evaluation summary from the training system")
    exported_at: Optional[datetime] = None
    installed_at: Optional[datetime] = None


class InvalidModelError(ValueError):
    pass


class NoModelError(LookupError):
    pass


@dataclass
class ActiveModel:
    manifest: ModelManifest
    detector: OpenVinoDetector
    path: str


class ModelStore:
    def __init__(self, model_dir: str, device: str = "CPU"):
        import openvino as ov

        self.model_dir = model_dir
        self.device = device
        self.core = ov.Core()
        os.makedirs(model_dir, exist_ok=True)
        self._active: Optional[ActiveModel] = None
        self._lock = threading.Lock()  # guards ``_active``
        self._install_lock = threading.Lock()  # one installation at a time

    # -- reading -----------------------------------------------------------------
    def active(self) -> Optional[ActiveModel]:
        with self._lock:
            return self._active

    def detect(self, image: np.ndarray, confidence: float) -> tuple[ActiveModel, DetectionResult]:
        model = self.active()  # keep a reference: a concurrent swap does not affect this request
        if model is None:
            raise NoModelError("no model installed yet")
        return model, model.detector.detect(image, confidence, model.manifest.nms_iou_threshold)

    # -- startup -----------------------------------------------------------------
    def load_active(self) -> None:
        """Load the model recorded in ``active.json`` (no model is fine: the API waits for an upload)."""
        try:
            with open(os.path.join(self.model_dir, ACTIVE_FILE), encoding="utf-8") as f:
                name = json.load(f)["dir"]
        except FileNotFoundError:
            log.warning("no model installed yet - upload one via PUT /api/v1/model")
            return
        try:
            model = self._load(os.path.join(self.model_dir, name))
        except Exception:
            log.exception("could not load the installed model %s", name)
            return
        with self._lock:
            self._active = model
        log.info("loaded model %s", model.manifest.version)

    # -- installation ------------------------------------------------------------
    def install(self, manifest: ModelManifest, xml: BinaryIO, weights: BinaryIO, max_bytes: int) -> ActiveModel:
        with self._install_lock:
            manifest = manifest.model_copy(update={"installed_at": datetime.now(timezone.utc)})
            stamp = manifest.installed_at.strftime("%Y%m%dT%H%M%S%fZ")
            name = f"{manifest.version}-{stamp}"
            staging = tempfile.mkdtemp(prefix=".incoming-", dir=self.model_dir)
            target = os.path.join(self.model_dir, name)
            try:
                _copy_limited(xml, os.path.join(staging, "model.xml"), max_bytes)
                _copy_limited(weights, os.path.join(staging, "model.bin"), max_bytes)
                with open(os.path.join(staging, "manifest.json"), "w", encoding="utf-8") as f:
                    f.write(manifest.model_dump_json(indent=2))
                os.replace(staging, target)
                model = self._load(target)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                shutil.rmtree(target, ignore_errors=True)
                raise
            _write_json_atomic(os.path.join(self.model_dir, ACTIVE_FILE), {"dir": name})
            with self._lock:
                previous, self._active = self._active, model
            log.info("activated model %s (previous: %s)", manifest.version, previous.manifest.version if previous else "none")
            self._remove_all_except(name)
            return model

    def _load(self, path: str) -> ActiveModel:
        try:
            with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
                manifest = ModelManifest.model_validate_json(f.read())
            validate_input_size(manifest.input_width, manifest.input_height)
        except (OSError, ValueError) as exc:
            raise InvalidModelError(f"invalid manifest: {exc}") from exc
        try:
            detector = OpenVinoDetector(self.core, os.path.join(path, "model.xml"), manifest.input_width,
                                        manifest.input_height, device=self.device)
            # test inference: proves the files are a usable detector and the class list matches
            _boxes, scores, _info = detector.infer_raw(np.zeros((manifest.input_height, manifest.input_width, 3), np.uint8))
        except Exception as exc:
            raise InvalidModelError(f"the model could not be loaded: {exc}") from exc
        num_scores = int(np.asarray(scores).reshape(-1, np.asarray(scores).shape[-1]).shape[1])
        if num_scores != len(manifest.class_names):
            raise InvalidModelError(
                f"the model outputs {num_scores} classes, but the manifest lists {len(manifest.class_names)}"
            )
        return ActiveModel(manifest, detector, path)

    def _remove_all_except(self, keep: str) -> None:
        for entry in os.listdir(self.model_dir):
            path = os.path.join(self.model_dir, entry)
            if entry != keep and os.path.isdir(path) and not entry.startswith(".incoming-"):
                # the previous detector may still finish in-flight requests: its files stay
                # readable until it is released (unlinked files keep their data on Linux)
                shutil.rmtree(path, ignore_errors=True)


def _copy_limited(src: BinaryIO, dst: str, max_bytes: int) -> None:
    size = 0
    with open(dst, "wb") as out:
        while chunk := src.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise InvalidModelError(f"model file exceeds {max_bytes // (1024 * 1024)} MB")
            out.write(chunk)
    if size == 0:
        raise InvalidModelError(f"{os.path.basename(dst)} is empty")


def _write_json_atomic(path: str, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".active-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)

