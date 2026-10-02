"""Deterministic train/validation split assignment."""
from __future__ import annotations

import hashlib

TRAIN = "train"
VALIDATION = "validation"


def assign_split(sha256: str, val_ratio: float) -> str:
    """Assign a split from the image content hash.

    The result only depends on the image content and the ratio, so it is
    reproducible. Once assigned, the split is persisted on the image and never
    re-rolled, even if the ratio changes later.
    """
    if not 0.0 <= val_ratio < 1.0:
        raise ValueError("val_ratio must be in [0, 1)")
    digest = hashlib.sha256(("split:" + sha256).encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") / 2**64
    return VALIDATION if bucket < val_ratio else TRAIN
