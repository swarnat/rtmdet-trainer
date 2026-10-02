from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class DetectionClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    label: str
    color: str
    coco_classes: list[str]
    sort_order: int
    active: bool
    annotation_count: int = 0
    created_at: datetime
    updated_at: datetime


class DetectionClassCreate(BaseModel):
    name: str = Field(..., description="Technischer Name (a-z, 0-9, _), unveränderlich", examples=["battery"])
    label: str = Field(..., min_length=1, max_length=64, examples=["Batterie"])
    color: Optional[str] = Field(None, pattern=COLOR_PATTERN)
    coco_classes: list[str] = Field(default_factory=list, description="COCO-Quellklassen, optional")


class DetectionClassUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=64)
    color: Optional[str] = Field(None, pattern=COLOR_PATTERN)
    coco_classes: Optional[list[str]] = None
    active: Optional[bool] = None


class ClassOrder(BaseModel):
    names: list[str] = Field(..., description="Alle Klassennamen in der gewünschten Reihenfolge")
