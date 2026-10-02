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
    source: Literal["manual", "prediction"] = "manual"


class AnnotationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: int
    class_name: str = Field(serialization_alias="class")
    x1: float
    y1: float
    x2: float
    y2: float
    source: str
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
    annotation_count: int = 0
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
