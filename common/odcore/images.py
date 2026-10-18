"""Image decoding/validation for uploads and inference requests (API and client annotator)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import decode_image

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}
THUMBNAIL_WIDTH = 384


@dataclass
class DecodedImage:
    data: bytes
    image: np.ndarray
    sha256: str
    content_type: str
    extension: str

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


def sniff_content_type(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return None


def decode_upload(data: bytes) -> DecodedImage:
    """Validate and decode uploaded image bytes. Raises ``ValueError``."""
    content_type = sniff_content_type(data)
    if content_type is None:
        raise ValueError("unsupported image format (allowed: JPEG, PNG, WebP, BMP)")
    if content_type == "image/jpeg" and not data.rstrip(b"\x00\r\n ").endswith(b"\xff\xd9"):
        # no end-of-image marker: incomplete download/transfer. OpenCV still "decodes" such files, and
        # the missing part is then filled with leftover memory (e.g. the previously decoded image).
        raise ValueError("truncated JPEG (incomplete file, e.g. interrupted download)")
    image = decode_image(data)
    return DecodedImage(
        data=data,
        image=image,
        sha256=hashlib.sha256(data).hexdigest(),
        content_type=content_type,
        extension=ALLOWED_CONTENT_TYPES[content_type],
    )


def make_thumbnail(image: np.ndarray, width: int = THUMBNAIL_WIDTH) -> bytes:
    h, w = image.shape[:2]
    if w > width:
        image = cv2.resize(image, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("could not encode thumbnail")
    return buf.tobytes()
