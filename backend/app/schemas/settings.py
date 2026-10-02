from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SettingsOut(BaseModel):
    values: dict[str, Any]
    defaults: dict[str, Any]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
