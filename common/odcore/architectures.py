"""Catalogue of selectable base models (COCO-pretrained RTMDet sizes).

Checkpoints come from the OpenMMLab MMDetection v3 model zoo (Apache-2.0,
trained on COCO 2017). The sha256 prefix is part of the official file name
and is verified after download.
"""
from __future__ import annotations

from dataclasses import dataclass

_ZOO = "https://download.openmmlab.com/mmdetection/v3.0/rtmdet"


@dataclass(frozen=True)
class BaseModel:
    id: str                 # value of TrainingRun.base_model_id, e.g. "rtmdet-m-coco"
    architecture: str       # stored on ModelVersion.architecture, e.g. "rtmdet-m"
    label: str
    config: str             # config path inside mmdet/.mim/configs
    checkpoint_url: str
    sha256_prefix: str
    coco_ap: float          # box AP on COCO val2017 (model zoo)
    params_m: float

    @property
    def checkpoint_key(self) -> str:
        """Location of the downloaded checkpoint in the ``models`` bucket."""
        return f"base/{self.config.split('/')[-1][:-3]}.pth"


BASE_MODELS: tuple[BaseModel, ...] = (
    BaseModel(
        "rtmdet-tiny-coco", "rtmdet-tiny", "RTMDet-tiny (COCO)", "rtmdet/rtmdet_tiny_8xb32-300e_coco.py",
        f"{_ZOO}/rtmdet_tiny_8xb32-300e_coco/rtmdet_tiny_8xb32-300e_coco_20220902_112414-78e30dcc.pth",
        "78e30dcc", 41.1, 4.8,
    ),
    BaseModel(
        "rtmdet-s-coco", "rtmdet-s", "RTMDet-S (COCO)", "rtmdet/rtmdet_s_8xb32-300e_coco.py",
        f"{_ZOO}/rtmdet_s_8xb32-300e_coco/rtmdet_s_8xb32-300e_coco_20220905_161602-387a891e.pth",
        "387a891e", 44.6, 8.9,
    ),
    BaseModel(
        "rtmdet-m-coco", "rtmdet-m", "RTMDet-M (COCO)", "rtmdet/rtmdet_m_8xb32-300e_coco.py",
        f"{_ZOO}/rtmdet_m_8xb32-300e_coco/rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth",
        "229f527c", 49.4, 24.7,
    ),
)
DEFAULT_BASE_MODEL = "rtmdet-s-coco"


def get_base_model(base_id: str) -> BaseModel:
    for m in BASE_MODELS:
        if m.id == base_id:
            return m
    raise KeyError(f"unknown base model '{base_id}'")


def base_model_for_architecture(architecture: str) -> BaseModel:
    for m in BASE_MODELS:
        if m.architecture == architecture:
            return m
    raise KeyError(f"unknown architecture '{architecture}'")
