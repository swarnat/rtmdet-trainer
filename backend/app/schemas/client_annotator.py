from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ClientAnnotatorStatus(BaseModel):
    configured: bool = Field(description="URL and access token are set in the settings")
    url: Optional[str]
    reachable: bool
    error: Optional[str]
    config: Optional[dict[str, Any]] = Field(description="configuration on the client (None = not pushed yet)")
    counts: Optional[dict[str, int]] = Field(description="images on the client: total, open, annotated")


class ClientImageSummary(BaseModel):
    id: int
    filename: Optional[str]
    status: Literal["open", "annotated"]
    annotations: int
    detections: Optional[int] = Field(description="detections of the latest check (None = not checked)")


class ClientImageList(BaseModel):
    counts: dict[str, int]
    items: list[ClientImageSummary]


class ClientImportResult(BaseModel):
    client_id: int
    filename: Optional[str] = None
    # deleted: the same file was deleted here earlier (tombstone) and is not imported again
    status: Literal["created", "duplicate", "deleted", "error"]
    image_id: Optional[int] = None
    # annotations: saved as labeled; suggestions: detections of the client check stored as suggestions;
    # kept: the image was already labeled here, its annotations were not replaced; none: nothing to apply
    applied: Literal["annotations", "suggestions", "kept", "none"] = "none"
    # removed from the client (only after a successful import)
    client_deleted: bool = False
    error: Optional[str] = None
