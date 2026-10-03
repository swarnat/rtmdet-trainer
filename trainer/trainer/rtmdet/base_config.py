"""RTMDet base models (tiny/S/M): MMDetection config and COCO-pretrained checkpoint.

Checkpoints come from the OpenMMLab MMDetection v3 model zoo (see
``odcore.architectures``). Each file is downloaded once, verified against the
sha256 prefix of its official name and kept in the ``models`` bucket under
``base/`` so later runs do not depend on the internet.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import time
import urllib.request

import torch

from odcore.architectures import BaseModel
from odcore.classes import COCO_CLASSES

from ..db import storage

log = logging.getLogger(__name__)

# RTMDet normalisation (BGR input, no channel swap)
MEAN = (103.53, 116.28, 123.675)
STD = (57.375, 57.12, 58.395)


def base_config_path(base: BaseModel) -> str:
    """Path of the RTMDet config shipped inside the mmdet package (``.mim``)."""
    import mmdet

    path = os.path.join(os.path.dirname(mmdet.__file__), ".mim", "configs", base.config)
    if not os.path.exists(path):
        raise FileNotFoundError(f"MMDetection config not found: {path}")
    return path


def load_base_config(base: BaseModel, num_classes: int):
    """RTMDet config of the given size, adapted for single-GPU/CPU use and the class count."""
    from mmengine.config import Config

    cfg = Config.fromfile(base_config_path(base))
    # No ImageNet backbone download: weights always come from a full detector checkpoint.
    cfg.model.backbone.init_cfg = None
    # SyncBN is only meaningful for multi-GPU training; plain BN keeps CPU export simple.
    for part in (cfg.model.backbone, cfg.model.neck, cfg.model.bbox_head):
        if "norm_cfg" in part:
            part.norm_cfg = dict(type="BN")
    cfg.model.bbox_head.num_classes = num_classes
    return cfg


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, path: str, attempts: int = 3, timeout: float = 60.0) -> None:
    """Download with socket timeout, retries and progress logging (the model zoo can be slow)."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as res, open(path, "wb") as f:
                total = int(res.headers.get("Content-Length") or 0)
                done, last_log = 0, time.monotonic()
                while chunk := res.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if time.monotonic() - last_log > 15:
                        last_log = time.monotonic()
                        pct = f" ({100 * done / total:.0f} %)" if total else ""
                        log.info("download: %.1f MB%s", done / 1e6, pct)
                if total and done != total:
                    raise OSError(f"incomplete download: {done} of {total} bytes")
            return
        except OSError as exc:
            log.warning("download attempt %d/%d failed: %s", attempt, attempts, exc)
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)


def ensure_base_checkpoint(base: BaseModel, local_dir: str) -> str:
    """Return a local path to the COCO checkpoint of ``base``, fetching it from S3 or the model zoo."""
    s3 = storage()
    bucket = s3.settings.bucket_models
    key = base.checkpoint_key
    os.makedirs(local_dir, exist_ok=True)
    path = os.path.join(local_dir, os.path.basename(key))
    if os.path.exists(path):
        return path
    if s3.exists(bucket, key):
        s3.download_file(bucket, key, path)
        return path

    log.info("downloading COCO-pretrained %s checkpoint from %s", base.label, base.checkpoint_url)
    tmp = path + ".part"
    _download(base.checkpoint_url, tmp)
    digest = _sha256(tmp)
    if not digest.startswith(base.sha256_prefix):
        os.remove(tmp)
        raise RuntimeError(f"checkpoint sha256 {digest} does not match expected prefix {base.sha256_prefix}")
    os.replace(tmp, path)
    s3.upload_file(bucket, key, path, "application/octet-stream")
    log.info("stored base checkpoint as s3://%s/%s (sha256 %s)", bucket, key, digest)
    return path


# RTMDet initialises the classification convs with N(0, 0.01) and a bias for prior probability 0.01
_CLS_BIAS_INIT = -math.log((1 - 0.01) / 0.01)


def _load_state(path: str) -> dict:
    ckpt = torch.load(path, map_location="cpu")
    return ckpt.get("state_dict", ckpt)


def build_init_checkpoint(
    source_ckpt: str,
    source_classes: list[str] | tuple[str, ...],
    target_classes: list[str],
    coco_mapping: dict[str, list[int]],
    out_path: str,
    coco_ckpt: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Create the initial checkpoint for a run with ``target_classes``.

    Backbone, neck and box regression are taken from ``source_ckpt``. Each row
    of the classification layers is initialised, per target class, from

    1. the same class in the source model (continue training), else
    2. the mean of its COCO source classes (``coco_mapping``; from the source
       if it is the COCO checkpoint, otherwise from ``coco_ckpt``), else
    3. fresh RTMDet initialisation (new class without COCO equivalent).

    Returns the path and a ``{class: origin}`` report for the log.
    """
    state = _load_state(source_ckpt)
    is_coco = tuple(source_classes) == COCO_CLASSES
    coco_state = state if is_coco else (_load_state(coco_ckpt) if coco_ckpt else None)
    report: dict[str, str] = {}
    new_state = {}
    for key, value in state.items():
        if not (key.startswith("bbox_head.rtm_cls.") and value.shape[0] == len(source_classes)):
            new_state[key] = value
            continue
        rows = []
        for name in target_classes:
            if name in source_classes and not is_coco:
                rows.append(value[list(source_classes).index(name)])
                report[name] = "source model"
            elif name in coco_mapping and coco_state is not None and key in coco_state:
                rows.append(coco_state[key][coco_mapping[name]].mean(dim=0))
                report[name] = "COCO " + "+".join(COCO_CLASSES[i] for i in coco_mapping[name])
            else:
                if key.endswith(".bias"):
                    rows.append(torch.full_like(value[0], _CLS_BIAS_INIT))
                else:
                    rows.append(torch.randn_like(value[0]) * 0.01)
                report[name] = "random (new class)"
        new_state[key] = torch.stack(rows, dim=0).clone()
    torch.save({"state_dict": new_state, "meta": {"classes": list(target_classes), "head_init": report}}, out_path)
    return out_path, report
