from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AnnotationIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # validated against the configured classes when saving
    class_name: str = Field(validation_alias="class", serialization_alias="class", max_length=32)
    x1: float
    y1: float
    x2: float
    y2: float
    # hard_negative = region a model wrongly detected as `class` (false positive)
    type: Literal["positive", "hard_negative"] = "positive"
    source: Literal["manual", "prediction"] = "manual"
    source_confidence: Optional[float] = Field(None, ge=0, le=1, description="hard negatives: confidence of the false detection")
    source_model: Optional[str] = Field(None, max_length=32, description="hard negatives: model version that produced it")


class AnnotationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: int
    class_name: str = Field(serialization_alias="class")
    x1: float
    y1: float
    x2: float
    y2: float
    type: str
    source: str
    source_confidence: Optional[float] = None
    source_model: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AnnotationsSave(BaseModel):
    """Replaces all annotations of an image and marks it as labeled.

    An empty list is valid: the image is then a negative training example.
    """

    annotations: list[AnnotationIn]
    mark_labeled: bool = True


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sha256: str
    original_filename: Optional[str]
    content_type: str
    size_bytes: int
    width: int
    height: int
    annotation_status: str
    dataset_split: Optional[str]
    annotation_count: int = Field(0, description="positive boxes")
    hard_negative_count: int = 0
    reviewed_classes: Optional[list[str]] = None
    # labeled, but not checked for all currently active classes
    needs_review: bool = False
    created_at: datetime
    updated_at: datetime
    labeled_at: Optional[datetime]


class ImageDetail(ImageOut):
    annotations: list[AnnotationOut]


class ImageList(BaseModel):
    total: int
    items: list[ImageOut]


class UploadResult(BaseModel):
    filename: Optional[str]
    status: Literal["created", "duplicate", "error"]
    image: Optional[ImageOut] = None
    error: Optional[str] = None


class ImageUpdate(BaseModel):
    annotation_status: Optional[Literal["unlabeled", "labeled"]] = None
    dataset_split: Optional[Literal["train", "validation"]] = None
