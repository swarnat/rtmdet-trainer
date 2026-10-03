"""Hard negatives: background crops for training and regression checks.

A hard negative is a region a model wrongly detected as a class (e.g. a sign
as ``person``). It is NOT trained as an extra class. Instead, for every hard
negative of a training image a crop around it is added to the training split:
the crop contains no positive box for the false detection, so RTMDet learns
via its normal background loss that this structure is not that class. Real
annotated objects inside the crop keep their (transformed, clipped) boxes.

Crop geometry: box enlarged by ``context_factor`` per side, widened to the
16:9 training aspect ratio and at least ``min_crop_fraction`` of the image
width. The minimum size matters because MMDetection scales every training
image to the model input size; a tiny crop would be magnified far beyond the
scale the structure has in real camera images.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import cv2

ASPECT = 16 / 9


@dataclass(frozen=True)
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


def compute_crop(img_w: int, img_h: int, box: tuple[float, float, float, float],
                 context_factor: float, min_crop_fraction: float, aspect: float = ASPECT) -> Rect:
    """Crop rectangle (integer pixels, inside the image) that contains ``box`` with context."""
    bx1, by1, bx2, by2 = box
    bw, bh = max(1.0, bx2 - bx1), max(1.0, by2 - by1)
    cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
    w, h = bw * context_factor, bh * context_factor
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    min_w = min_crop_fraction * img_w
    if w < min_w:
        w, h = min_w, min_w / aspect
    # fit into the image (keeping the aspect ratio where possible), but never cut the box itself
    scale = min(1.0, img_w / w, img_h / h)
    w, h = max(w * scale, bw), max(h * scale, bh)
    w, h = min(w, img_w), min(h, img_h)
    x1 = min(max(0.0, cx - w / 2), img_w - w)
    y1 = min(max(0.0, cy - h / 2), img_h - h)
    rx1, ry1 = int(round(x1)), int(round(y1))
    return Rect(rx1, ry1, min(img_w, rx1 + int(round(w))), min(img_h, ry1 + int(round(h))))


def transform_boxes(boxes: list[tuple[str, float, float, float, float]], crop: Rect,
                    min_size: float = 1.0) -> list[tuple[str, float, float, float, float]]:
    """Clip ``(class, x1, y1, x2, y2)`` boxes to the crop and shift them into crop coordinates.

    Boxes with a visible part larger than ``min_size`` in both directions are
    kept (same rule as MMDetection's RandomCrop).
    """
    out = []
    for cls, x1, y1, x2, y2 in boxes:
        nx1, ny1 = max(x1, crop.x1) - crop.x1, max(y1, crop.y1) - crop.y1
        nx2, ny2 = min(x2, crop.x2) - crop.x1, min(y2, crop.y2) - crop.y1
        if nx2 - nx1 > min_size and ny2 - ny1 > min_size:
            out.append((cls, nx1, ny1, nx2, ny2))
    return out


def write_crop(image_path: str, crop: Rect, out_path: str) -> None:
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"cannot read {image_path}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if not cv2.imwrite(out_path, image[crop.y1 : crop.y2, crop.x1 : crop.x2], [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise RuntimeError(f"cannot write {out_path}")
