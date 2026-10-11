"""Upload validation."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.services.preprocessing import decode_upload


def jpeg() -> bytes:
    image = np.random.default_rng(1).integers(0, 255, (360, 640, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


def test_complete_jpeg_is_accepted_also_with_padding():
    assert decode_upload(jpeg()).width == 640
    assert decode_upload(jpeg() + b"\x00\x00").width == 640


def test_truncated_jpeg_is_rejected():
    # OpenCV would decode this and fill the missing rows with whatever is in memory
    with pytest.raises(ValueError, match="truncated JPEG"):
        decode_upload(jpeg()[:4038])
