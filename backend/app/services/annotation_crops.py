"""Crops of annotated boxes for the annotation review page (box + a margin of context)."""
from __future__ import annotations

import threading
from collections import OrderedDict

import cv2
import numpy as np

from odcore.geometry import decode_image

CROP_MARGIN = 20  # original pixels around the box
CROP_MAX_SIDE = 320  # larger crops are downscaled (the page shows them small anyway)


def crop_window(x1: float, y1: float, x2: float, y2: float, width: int, height: int,
                margin: int = CROP_MARGIN) -> tuple[int, int, int, int]:
    """Box plus ``margin``, clipped to the image. Same formula as the frontend overlay."""
    return (max(0, int(np.floor(x1 - margin))), max(0, int(np.floor(y1 - margin))),
            min(width, int(np.ceil(x2 + margin))), min(height, int(np.ceil(y2 + margin))))


def crop_jpeg(image: np.ndarray, box: tuple[float, float, float, float], margin: int = CROP_MARGIN,
              max_side: int = CROP_MAX_SIDE) -> bytes:
    h, w = image.shape[:2]
    cx1, cy1, cx2, cy2 = crop_window(*box, w, h, margin)
    crop = image[cy1:max(cy2, cy1 + 1), cx1:max(cx2, cx1 + 1)]
    scale = max_side / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, (max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale))),
                          interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("could not encode crop")
    return buf.tobytes()


class DecodedCache:
    """A few decoded originals: the page loads all crops of an image at once (one S3 download per image)."""

    def __init__(self, size: int = 12):
        self.size = size
        self._items: OrderedDict[int, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, image_id: int, load) -> np.ndarray:
        with self._lock:
            if image_id in self._items:
                self._items.move_to_end(image_id)
                return self._items[image_id]
        image = decode_image(load())
        with self._lock:
            self._items[image_id] = image
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return image


decoded_cache = DecodedCache()
