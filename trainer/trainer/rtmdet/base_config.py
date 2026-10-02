"""RTMDet-S base model: MMDetection config and the COCO-pretrained checkpoint.

Checkpoint origin: OpenMMLab MMDetection v3 model zoo,
``rtmdet_s_8xb32-300e_coco_20220905_161602-387a891e.pth`` (COCO 2017 train,
44.6 box AP on val2017). The file is downloaded once and kept in the
``models`` bucket under ``base/`` so later runs do not depend on the internet.
"""
from __future__ import annotations

import hashlib
import logging
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


def make_head_initialised_checkpoint(coco_ckpt: str, mapping: dict[str, list[int]], class_names: tuple[str, ...], out_path: str) -> str:
    """Create a 3-class checkpoint from the 80-class COCO checkpoint.

    Backbone, neck and box regression are reused as-is. The classification
    layers are initialised from the matching COCO classes (mean of the source
    rows, e.g. vehicle = mean(car, motorcycle, bus, truck)) instead of random
    weights, which helps a lot on small datasets.
    """
    ckpt = torch.load(coco_ckpt, map_location="cpu")
    state = ckpt.get("state_dict", ckpt)
    new_state = {}
    for key, value in state.items():
        if key.startswith("bbox_head.rtm_cls.") and value.shape[0] == len(COCO_CLASSES):
            rows = [value[mapping[name]].mean(dim=0) for name in class_names]
            new_state[key] = torch.stack(rows, dim=0).clone()
        else:
            new_state[key] = value
    torch.save({"state_dict": new_state, "meta": {"source": "rtmdet-s-coco", "class_mapping": mapping}}, out_path)
    return out_path
