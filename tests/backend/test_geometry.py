"""Bounding-box conversion, scaling and letterboxing."""
from __future__ import annotations

import numpy as np
import pytest

from odcore.geometry import (
    PAD_VALUE,
    boxes_input_to_original,
    boxes_original_to_input,
    compute_letterbox,
    letterbox,
    nms,
    normalize_box,
    parse_input_size,
    postprocess,
    to_model_input,
    xywh_to_xyxy,
    xyxy_to_xywh,
)


@pytest.mark.parametrize(
    "orig,inp,scale,resized",
    [
        ((1920, 1080), (1536, 864), 0.8, (1536, 864)),     # 16:9 -> 16:9, no padding
        ((3840, 2160), (1536, 864), 0.4, (1536, 864)),
        ((1280, 720), (1536, 864), 1.2, (1536, 864)),      # upscaling
        ((1600, 1200), (1536, 864), 0.72, (1152, 864)),    # 4:3 -> padded right
        ((2000, 500), (1536, 864), 0.768, (1536, 384)),    # very wide -> padded bottom
    ],
)
def test_compute_letterbox(orig, inp, scale, resized):
    info = compute_letterbox(*orig, *inp)
    assert info.scale == pytest.approx(scale)
    assert (info.resized_width, info.resized_height) == resized
    assert info.resized_width <= inp[0] and info.resized_height <= inp[1]


def test_letterbox_keeps_aspect_ratio_and_pads():
    image = np.full((1200, 1600, 3), 200, dtype=np.uint8)
    canvas, info = letterbox(image, 1536, 864)
    assert canvas.shape == (864, 1536, 3)
    assert info.resized_width == 1152
    # image content top-left, padding right
    assert (canvas[:, :1152] == 200).all()
    assert (canvas[:, 1152:] == PAD_VALUE).all()


def test_letterbox_16_9_has_no_padding():
    image = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    canvas, info = letterbox(image, 1536, 864)
    assert canvas.shape == (864, 1536, 3)
    assert (info.resized_width, info.resized_height) == (1536, 864)


def test_to_model_input_layout():
    canvas = np.zeros((864, 1536, 3), dtype=np.uint8)
    canvas[..., 2] = 7
    tensor = to_model_input(canvas)
    assert tensor.shape == (1, 3, 864, 1536)
    assert tensor.dtype == np.float32
    assert (tensor[0, 2] == 7).all()


@pytest.mark.parametrize("orig", [(1920, 1080), (1600, 1200), (1280, 720)])
def test_box_roundtrip_original_input_original(orig):
    info = compute_letterbox(*orig, 1536, 864)
    boxes = np.array([[10, 20, 300, 400], [0, 0, orig[0], orig[1]]], dtype=np.float64)
    back = boxes_input_to_original(boxes_original_to_input(boxes, info), info)
    np.testing.assert_allclose(back, boxes, atol=1e-6)


def test_input_to_original_scales_and_clips():
    info = compute_letterbox(1920, 1080, 1536, 864)
    out = boxes_input_to_original(np.array([[400, 160, 560, 640], [-10, -10, 1600, 900]]), info)
    np.testing.assert_allclose(out[0], [500, 200, 700, 800])
    np.testing.assert_allclose(out[1], [0, 0, 1920, 1080])  # clipped to the original image


def test_normalize_box_orders_and_clips():
    assert normalize_box(50, 80, 10, 20, 100, 100) == (10, 20, 50, 80)
    assert normalize_box(-5, -5, 120, 50, 100, 100) == (0, 0, 100, 50)
    with pytest.raises(ValueError):
        normalize_box(10, 10, 10.5, 50, 100, 100)
    with pytest.raises(ValueError):
        normalize_box(200, 200, 300, 300, 100, 100)


def test_xywh_conversion():
    assert xyxy_to_xywh((10, 20, 110, 70)) == [10, 20, 100, 50]
    assert xywh_to_xyxy([10, 20, 100, 50]) == (10, 20, 110, 70)


@pytest.mark.parametrize("value,expected", [("1536x864", (1536, 864)), ("1280 x 736", (1280, 736)), ("1024×576", (1024, 576))])
def test_parse_input_size(value, expected):
    assert parse_input_size(value) == expected


@pytest.mark.parametrize("value", ["1536", "1530x864", "abc", "0x0", "8192x4608"])
def test_parse_input_size_invalid(value):
    with pytest.raises(ValueError):
        parse_input_size(value)


def test_nms_removes_overlaps():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    assert nms(boxes, scores, 0.5).tolist() == [0, 2]


def test_postprocess_maps_to_original_coordinates():
    info = compute_letterbox(1920, 1080, 1536, 864)
    boxes = np.array([[400, 160, 560, 640], [404, 164, 562, 642], [800, 400, 1000, 600]], dtype=np.float32)
    scores = np.array([[0.9, 0, 0], [0.8, 0, 0], [0, 0, 0.6]], dtype=np.float32)
    dets = postprocess(boxes, scores, info, score_threshold=0.25, iou_threshold=0.6)
    assert [(d.class_id, round(d.confidence, 2)) for d in dets] == [(0, 0.9), (2, 0.6)]
    assert (dets[0].x1, dets[0].y1, dets[0].x2, dets[0].y2) == pytest.approx((500, 200, 700, 800))
    assert (dets[1].x1, dets[1].y1, dets[1].x2, dets[1].y2) == pytest.approx((1000, 500, 1250, 750))


def test_postprocess_classwise_nms_keeps_other_class():
    info = compute_letterbox(1536, 864, 1536, 864)
    boxes = np.array([[0, 0, 100, 100], [0, 0, 100, 100]], dtype=np.float32)
    scores = np.array([[0.9, 0.0, 0.0], [0.0, 0.8, 0.0]], dtype=np.float32)
    assert len(postprocess(boxes, scores, info, 0.25)) == 2
