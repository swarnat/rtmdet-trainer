from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    version: str
    status: str
    kind: str
    architecture: str
    checkpoint_key: str
    onnx_key: str
    openvino_key: str
    config_key: Optional[str]
    input_width: int
    input_height: int
    class_names: list[str]
    class_mapping_json: Optional[dict[str, Any]]
    metrics_json: Optional[dict[str, Any]]
    dataset_snapshot: Optional[str]
    training_run_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    activated_at: Optional[datetime]


class ModelVersionUpdate(BaseModel):
    notes: Optional[str] = None


class BenchmarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    status: str
    class_names: Optional[list[str]] = None
    num_images: int
    num_boxes: int
    num_hard_negatives: int
    total: int
    processed: int
    # {version: metrics (as stored with a model, plus "status") | {"status", "error"}}
    results: dict[str, Any] = Field(validation_alias="results_json")
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
