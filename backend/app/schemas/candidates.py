from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CandidateSearchIn(BaseModel):
    class_name: str = Field(validation_alias="class", max_length=64, description="class the candidates are for (must be active)")
    mode: Literal["text", "examples"] = "text"
    prompts: list[str] = Field(default_factory=list, max_length=10, description="mode text: text queries, e.g. 'excavator'")
    exemplar_ids: list[int] = Field(
        default_factory=list, max_length=20,
        description="mode examples: ids of annotations (any class) whose boxes show what to look for",
    )
    scope: Literal["all", "labeled", "unlabeled"] = "all"
    max_images: int = Field(0, ge=0, le=1_000_000, description="0 = all images of the scope")
    min_score: float = Field(0.1, ge=0.01, le=0.95)

    model_config = ConfigDict(populate_by_name=True)


class CandidateSearchOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: int
    class_name: str = Field(serialization_alias="class")
    mode: str = "text"
    prompts: list[str]
    # number of example boxes (mode "examples")
    examples: int = 0
    scope: str
    max_images: int
    min_score: float
    status: str
    total: int
    processed: int
    found: int
    pending: int = 0
    accepted: int = 0
    rejected: int = 0
    model: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class CandidateOut(BaseModel):
    id: int
    image_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    prompt: str
    status: str
    image_width: int
    image_height: int
    # what accepting does: "new" = add a box, "reclassify" = an existing box of `current_class` becomes the
    # searched class, "exists" = the image already has such a box
    action: Literal["new", "reclassify", "exists"] = "new"
    current_class: Optional[str] = None


class CandidateList(BaseModel):
    total: int
    margin: int
    items: list[CandidateOut]


class CandidateDecision(BaseModel):
    accept: list[int] = Field(default_factory=list, max_length=2000)
    reject: list[int] = Field(default_factory=list, max_length=2000)


class CandidateDecisionResult(BaseModel):
    added: int = 0
    reclassified: int = 0
    already_present: int = 0
    rejected: int = 0
