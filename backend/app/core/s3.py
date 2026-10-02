from __future__ import annotations

from functools import lru_cache

from odcore.storage import ObjectStorage

from .config import get_settings


@lru_cache
def get_storage() -> ObjectStorage:
    return ObjectStorage(get_settings().s3())
