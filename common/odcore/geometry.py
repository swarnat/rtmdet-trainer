"""Letterboxing, coordinate conversion and post-processing.

All coordinates handed to clients are pixel coordinates of the *original*
image. The model works on a letterboxed image of a fixed input size: the
original is scaled uniformly (aspect ratio preserved) and placed in the
top-left corner; the remaining area on the right/bottom is padded with the
value 114 (same convention as MMDetection's ``Resize(keep_ratio=True)`` +
``Pad`` used during RTMDet training/validation).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

PAD_VALUE = 114
STRIDE_MULTIPLE = 32

_SIZE_RE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")


def parse_input_size(value: str) -> tuple[int, int]:
    """Parse ``"1536x864"`` into ``(width, height)`` and validate it."""
    match = _SIZE_RE.match(value or "")
    if not match:
        raise ValueError(f"invalid input size '{value}', expected WIDTHxHEIGHT")
    width, height = int(match.group(1)), int(match.group(2))
    validate_input_size(width, height)
    return width, height


def validate_input_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("input size must be positive")
    if width % STRIDE_MULTIPLE or height % STRIDE_MULTIPLE:
        raise ValueError(
            f"input size {width}x{height} must be a multiple of {STRIDE_MULTIPLE}"
        )
    if width > 4096 or height > 4096:
        raise ValueError("input size must not exceed 4096 pixels per side")


def format_input_size(width: int, height: int) -> str:
    return f"{width}x{height}"


@dataclass(frozen=True)
class LetterboxInfo:
    """Parameters of a letterbox transform original -> model input."""

    scale: float
    orig_width: int
    orig_height: int
    input_width: int
    input_height: int
    resized_width: int
    resized_height: int


def compute_letterbox(orig_width: int, orig_height: int, input_width: int, input_height: int) -> LetterboxInfo:
    if orig_width <= 0 or orig_height <= 0:
        raise ValueError("image size must be positive")
    scale = min(input_width / orig_width, input_height / orig_height)
    # Same rounding as mmcv.imrescale
    resized_w = min(input_width, int(orig_width * scale + 0.5))
    resized_h = min(input_height, int(orig_height * scale + 0.5))
    return LetterboxInfo(scale, orig_width, orig_height, input_width, input_height, resized_w, resized_h)


def letterbox(image: np.ndarray, input_width: int, input_height: int) -> tuple[np.ndarray, LetterboxInfo]:
    """Resize ``image`` (HxWx3, uint8) into a padded canvas of the input size."""
    h, w = image.shape[:2]
    info = compute_letterbox(w, h, input_width, input_height)
    if (info.resized_width, info.resized_height) != (w, h):
        interp = cv2.INTER_AREA if info.scale < 1 else cv2.INTER_LINEAR
        resized = cv2.resize(image, (info.resized_width, info.resized_height), interpolation=interp)
    else:
        resized = image
    canvas = np.full((input_height, input_width, 3), PAD_VALUE, dtype=np.uint8)
    canvas[: info.resized_height, : info.resized_width] = resized
    return canvas, info


def to_model_input(canvas: np.ndarray) -> np.ndarray:
    """HxWx3 uint8 BGR -> 1x3xHxW float32 (normalization happens inside the model)."""
    return np.ascontiguousarray(canvas.transpose(2, 0, 1)[None].astype(np.float32))


def boxes_input_to_original(boxes: np.ndarray, info: LetterboxInfo) -> np.ndarray:
    """Map ``Nx4`` xyxy boxes from model-input pixels to original-image pixels."""
    out = np.asarray(boxes, dtype=np.float64).reshape(-1, 4) / info.scale
    out[:, [0, 2]] = out[:, [0, 2]].clip(0, info.orig_width)
    out[:, [1, 3]] = out[:, [1, 3]].clip(0, info.orig_height)
    return out


def boxes_original_to_input(boxes: np.ndarray, info: LetterboxInfo) -> np.ndarray:
    """Map ``Nx4`` xyxy boxes from original-image pixels to model-input pixels."""
    return np.asarray(boxes, dtype=np.float64).reshape(-1, 4) * info.scale


def normalize_box(x1: float, y1: float, x2: float, y2: float, width: int, height: int) -> tuple[float, float, float, float]:
    """Order corners and clip a box to the image. Raises for degenerate boxes."""
    x1, x2 = sorted((float(x1), float(x2)))
    y1, y2 = sorted((float(y1), float(y2)))
    x1, x2 = max(0.0, x1), min(float(width), x2)
    y1, y2 = max(0.0, y1), min(float(height), y2)
    if x2 - x1 < 1 or y2 - y1 < 1:
        raise ValueError("bounding box is smaller than 1 pixel or outside the image")
    return x1, y1, x2, y2


def xyxy_to_xywh(box: tuple[float, float, float, float]) -> list[float]:
    """xyxy -> COCO [x, y, w, h]."""
    x1, y1, x2, y2 = box
    return [x1, y1, x2 - x1, y2 - y1]


def xywh_to_xyxy(box: list[float]) -> tuple[float, float, float, float]:
    x, y, w, h = box
    return x, y, x + w, y + h


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between ``Nx4`` and ``Mx4`` xyxy boxes."""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 4)
    area_a = (a[:, 2] - a[:, 0]).clip(0) * (a[:, 3] - a[:, 1]).clip(0)
    area_b = (b[:, 2] - b[:, 0]).clip(0) * (b[:, 3] - b[:, 1]).clip(0)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = (rb - lt).clip(0).prod(axis=2)
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)


# a detection covered at least this much by an ignore region is neither a true nor a false positive
IGNORE_COVERAGE = 0.5


def box_ioa(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise intersection over the area of ``a`` (share of ``a`` covered by ``b``): ``Nx4`` vs ``Mx4`` xyxy boxes.

    The overlap COCO uses for ``iscrowd`` regions (detections inside an ignore region are not counted).
    """
    a = np.asarray(a, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 4)
    area_a = (a[:, 2] - a[:, 0]).clip(0) * (a[:, 3] - a[:, 1]).clip(0)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = (rb - lt).clip(0).prod(axis=2)
    return np.where(area_a[:, None] > 0, inter / np.maximum(area_a[:, None], 1e-12), 0.0)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
    """Greedy NMS, returns kept indices sorted by descending score."""
    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        ious = box_iou(boxes[i : i + 1], boxes[order[1:]])[0]
        order = order[1:][ious <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


@dataclass(frozen=True)
class Detection:
    class_id: int
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def postprocess(
    boxes: np.ndarray,
    scores: np.ndarray,
    info: LetterboxInfo,
    score_threshold: float,
    iou_threshold: float = 0.6,
    pre_nms_top_k: int = 1000,
    max_detections: int = 300,
) -> list[Detection]:
    """Turn raw model outputs into final detections in original coordinates.

    ``boxes``: ``Nx4`` xyxy in model-input pixels, ``scores``: ``NxC`` sigmoid
    class scores. Uses multi-label candidate selection (one candidate per
    prior and class above threshold) followed by class-wise NMS, like RTMDet.
    """
    boxes = np.asarray(boxes, dtype=np.float32).reshape(-1, 4)
    scores = np.asarray(scores, dtype=np.float32)
    scores = scores.reshape(boxes.shape[0], -1)
    prior_idx, class_idx = np.nonzero(scores > score_threshold)
    if prior_idx.size == 0:
        return []
    cand_scores = scores[prior_idx, class_idx]
    if cand_scores.size > pre_nms_top_k:
        top = np.argpartition(-cand_scores, pre_nms_top_k)[:pre_nms_top_k]
        prior_idx, class_idx, cand_scores = prior_idx[top], class_idx[top], cand_scores[top]
    cand_boxes = boxes_input_to_original(boxes[prior_idx], info)

    results: list[Detection] = []
    for cls in np.unique(class_idx):
        mask = class_idx == cls
        cb, cs = cand_boxes[mask], cand_scores[mask]
        valid = ((cb[:, 2] - cb[:, 0]) > 0) & ((cb[:, 3] - cb[:, 1]) > 0)
        cb, cs = cb[valid], cs[valid]
        for k in nms(cb, cs, iou_threshold):
            x1, y1, x2, y2 = cb[k]
            results.append(Detection(int(cls), float(cs[k]), float(x1), float(y1), float(x2), float(y2)))
    results.sort(key=lambda d: d.confidence, reverse=True)
    return results[:max_detections]


def decode_image(data: bytes) -> np.ndarray:
    """Decode image bytes into a BGR uint8 array (EXIF orientation applied)."""
    if not data:
        raise ValueError("empty image")
    buf = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("unsupported or corrupt image")
    return image
