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


class DetectUrlRequest(BaseModel):
    url: str = Field(description="HTTP(S) URL of the image", examples=["https://example.com/cam1.jpg"])
    model: str | None = Field(default=None, description="'production' (default), 'candidate' or a version like 'model-0003'")
    input_size: str | None = Field(default=None, description="Model input size WIDTHxHEIGHT, e.g. 1536x864")
    confidence: float | None = Field(default=None, description="Confidence threshold, default 0.25")


class DetectUrlResponse(DetectResponse):
    image_data_url: str = Field(description="The downloaded image as data URL (for display; the URL may only be reachable from the server)")
