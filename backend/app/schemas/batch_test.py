from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class BatchTestCreate(BaseModel):
    model: str = Field("production", description="'production', 'candidate' or a version like 'model-0003'")
    input_size: Optional[str] = Field(None, description="WIDTHxHEIGHT; default: setting default_input_size")
    confidence: Optional[float] = Field(None, gt=0, le=1, description="default: setting default_confidence")
    scope: Literal["unlabeled", "unlabeled_and_review"] = Field(
        "unlabeled", description="open images only, or additionally labeled images that still need review for new classes"
    )


class BatchTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    status: str
    model_ref: str
    model_version: Optional[str]
    input_width: int
    input_height: int
    confidence: float
    scope: str
    total: int
    processed: int
    detections: int
    failed_images: int
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    batch_id: Optional[int]
    model_version: str
    input_width: int
    input_height: int
    confidence: float
    detections: list[dict[str, Any]] = Field(validation_alias="detections_json")
    created_at: datetime
