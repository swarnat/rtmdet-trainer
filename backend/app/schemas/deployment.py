from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DeployRequest(BaseModel):
    version: str = Field(examples=["model-0004"])


class DeploymentStatus(BaseModel):
    configured: bool = Field(description="URL and access key are set in the settings")
    url: Optional[str]
    reachable: bool
    model: Optional[dict[str, Any]] = Field(description="active model of the production system (None = none installed)")
    error: Optional[str]
    warnings: list[str] = Field(default_factory=list, description="problems reported by the production system")
