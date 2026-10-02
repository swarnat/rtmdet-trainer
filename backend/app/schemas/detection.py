from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class DetectionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_name: str = Field(serialization_alias="class", validation_alias="class", examples=["person"])
    confidence: float
    bbox: BBox


class ImageInfo(BaseModel):
    width: int
    height: int


class ModelInfo(BaseModel):
    version: str
    status: str
    input_width: int
    input_height: int


class DetectResponse(BaseModel):
    image: ImageInfo
    model: ModelInfo
    inference_ms: float = Field(description="Preprocessing + inference + postprocessing time in milliseconds")
    detections: list[DetectionOut]
