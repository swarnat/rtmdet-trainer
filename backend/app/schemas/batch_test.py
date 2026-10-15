from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class BatchTestCreate(BaseModel):
    model: str = Field("production", description="'production', 'candidate' or a version like 'model-0003'")
    input_size: Optional[str] = Field(None, description="WIDTHxHEIGHT; default: setting default_input_size")
    confidence: Optional[float] = Field(None, gt=0, le=1, description="default: setting default_confidence")
    scope: Literal["unlabeled", "unlabeled_and_review", "unlabeled_last_upload", "unlabeled_untested", "errors_validation", "errors_labeled"] = Field(
        "unlabeled",
        description="open images only, or additionally labeled images that still need review for new classes, or the "
        "open images of the most recent upload session (pauses < 30 min), or the open images no batch test has run on yet; "
        "errors_*: error analysis on labeled validation images / all labeled images",
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
    # error analysis: number of images with false positives / false negatives (``detections`` = number of errors)
    marked_images: int = 0
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


class ErrorMarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    batch_id: Optional[int]
    model_version: str
    input_width: int
    input_height: int
    confidence: float
    true_positives: int
    false_positives: list[dict[str, Any]] = Field(validation_alias="false_positives_json")
    false_negatives: list[dict[str, Any]] = Field(validation_alias="false_negatives_json")
    created_at: datetime
