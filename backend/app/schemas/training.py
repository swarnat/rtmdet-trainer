from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TrainingCreate(BaseModel):
    base_model_id: str = Field("rtmdet-s-coco", description="'rtmdet-s-coco' or an existing model version, e.g. 'model-0002'")
    class_names: Optional[list[str]] = Field(None, description="Classes to train (default: all active classes, in configured order)")
    input_size: str = Field("1536x864", examples=["1536x864"])
    epochs: int = Field(30, ge=1, le=1000)
    batch_size: int = Field(4, ge=1, le=128)
    learning_rate: Optional[float] = Field(None, gt=0, le=1)
    num_workers: int = Field(4, ge=0, le=32)


class TrainingRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    base_model_id: str
    class_names: Optional[list[str]]
    dataset_snapshot: Optional[str]
    dataset_stats_json: Optional[dict[str, Any]]
    input_width: int
    input_height: int
    epochs: int
    batch_size: int
    learning_rate: Optional[float]
    params_json: Optional[dict[str, Any]]
    progress_json: Optional[dict[str, Any]]
    metrics_json: Optional[dict[str, Any]]
    error: Optional[str]
    model_version: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class TrainingLog(BaseModel):
    id: int
    status: str
    log: str


class BaseModelOption(BaseModel):
    id: str
    label: str
    description: str


class SplitCount(BaseModel):
    train: int
    validation: int


class TrainingEligibility(BaseModel):
    class_names: list[str]
    usable: SplitCount = Field(description="labeled images checked for all selected classes")
    needs_review: int = Field(description="labeled images not (yet) checked for all selected classes, excluded")
    negative: int = Field(description="usable images without boxes of the selected classes")
