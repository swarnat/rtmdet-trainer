from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.batch_test import ErrorMarkOut, SuggestionOut


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
    # number of open batch-test suggestions (None = no suggestions stored)
    suggestion_count: Optional[int] = None
    # latest error analysis: false positives / false negatives of the model on this image (None = not marked)
    error_fp: Optional[int] = None
    error_fn: Optional[int] = None
    # empty image that is visually identical to this image (duplicate check); not used for training
    duplicate_of: Optional[int] = None
    duplicate_score: Optional[float] = None
    # reviewed on the duplicates page and kept
    duplicate_keep: bool = False
    reviewed_classes: Optional[list[str]] = None
    # labeled, but not checked for all currently active classes
    needs_review: bool = False
    # link count: training snapshots (models) that use this image
    snapshot_refs: int = 0
    created_at: datetime
    updated_at: datetime
    labeled_at: Optional[datetime]


class ImageDetail(ImageOut):
    annotations: list[AnnotationOut]
    suggestion: Optional[SuggestionOut] = None
    error_mark: Optional[ErrorMarkOut] = None


class DuplicateGroup(BaseModel):
    original: ImageOut
    duplicates: list[ImageOut]


class CameraGroupImage(BaseModel):
    image: ImageOut
    # image to blink-compare with: a labeled negative ("negative") or the previous image of the group ("previous")
    compare_with: Optional[int] = None
    compare_kind: Optional[Literal["negative", "previous"]] = None


class CameraGroup(BaseModel):
    # camera identity from the metadata ("" = unknown)
    camera: str = ""
    images: list[CameraGroupImage]


class CameraGroups(BaseModel):
    groups: list[CameraGroup]
    # open images never batch-tested: not part of the review
    untested: int = 0


class DuplicateResolve(BaseModel):
    keep: list[int] = Field(default_factory=list)
    delete: list[int] = Field(default_factory=list)


class ImageList(BaseModel):
    total: int
    items: list[ImageOut]


class UploadResult(BaseModel):
    filename: Optional[str]
    # deleted: the same file was deleted earlier (tombstone) and is not imported again
    status: Literal["created", "duplicate", "deleted", "error"]
    image: Optional[ImageOut] = None
    error: Optional[str] = None


class UrlDownload(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048, description="http(s) URL of a JPEG/PNG/WebP/BMP image")


class ImageUpdate(BaseModel):
    annotation_status: Optional[Literal["unlabeled", "labeled"]] = None
    dataset_split: Optional[Literal["train", "validation"]] = None
