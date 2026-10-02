"""RTMDet-S base model: MMDetection config and the COCO-pretrained checkpoint.

Checkpoint origin: OpenMMLab MMDetection v3 model zoo,
``rtmdet_s_8xb32-300e_coco_20220905_161602-387a891e.pth`` (COCO 2017 train,
44.6 box AP on val2017). The file is downloaded once and kept in the
``models`` bucket under ``base/`` so later runs do not depend on the internet.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import urllib.request

import torch

from odcore.classes import COCO_CLASSES

from ..config import get_settings
from ..db import storage

log = logging.getLogger(__name__)

BASE_MODEL_ID = "rtmdet-s-coco"
BASE_CONFIG_NAME = "rtmdet/rtmdet_s_8xb32-300e_coco.py"
BASE_CHECKPOINT_KEY = "base/rtmdet_s_8xb32-300e_coco.pth"
# RTMDet normalisation (BGR input, no channel swap)
MEAN = (103.53, 116.28, 123.675)
STD = (57.375, 57.12, 58.395)


def base_config_path() -> str:
    """Path of the RTMDet-S config shipped inside the mmdet package (``.mim``)."""
    import mmdet

    path = os.path.join(os.path.dirname(mmdet.__file__), ".mim", "configs", BASE_CONFIG_NAME)
    if not os.path.exists(path):
        raise FileNotFoundError(f"MMDetection config not found: {path}")
    return path


def load_base_config(num_classes: int):
    """RTMDet-S config adapted for single-GPU/CPU use and the given class count."""
    from mmengine.config import Config

    cfg = Config.fromfile(base_config_path())
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


def ensure_base_checkpoint(local_dir: str) -> str:
    """Return a local path to the COCO checkpoint, fetching it from S3 or the model zoo."""
    settings = get_settings()
    s3 = storage()
    bucket = s3.settings.bucket_models
    os.makedirs(local_dir, exist_ok=True)
    path = os.path.join(local_dir, os.path.basename(BASE_CHECKPOINT_KEY))
    if os.path.exists(path):
        return path
    if s3.exists(bucket, BASE_CHECKPOINT_KEY):
        s3.download_file(bucket, BASE_CHECKPOINT_KEY, path)
        return path

    log.info("downloading COCO-pretrained RTMDet-S checkpoint from %s", settings.base_checkpoint_url)
    tmp = path + ".part"
    urllib.request.urlretrieve(settings.base_checkpoint_url, tmp)
    digest = _sha256(tmp)
    prefix = settings.base_checkpoint_sha256_prefix.strip().lower()
    if prefix and not digest.startswith(prefix):
        os.remove(tmp)
        raise RuntimeError(f"checkpoint sha256 {digest} does not match expected prefix {prefix}")
    os.replace(tmp, path)
    s3.upload_file(bucket, BASE_CHECKPOINT_KEY, path, "application/octet-stream")
    log.info("stored base checkpoint as s3://%s/%s (sha256 %s)", bucket, BASE_CHECKPOINT_KEY, digest)
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
