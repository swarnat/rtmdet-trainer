"""Inference server fixtures: a real OpenVINO model with constant outputs, built in-process."""
from __future__ import annotations

import io
import json
import os

ACCESS_KEY = "test-access-key-0123456789"
os.environ["MODEL_UPLOAD_KEY"] = ACCESS_KEY

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

# Fixed raw model outputs in model-input pixels for a 1536x864 input
RAW_BOXES = np.array(
    [
        [400.0, 160.0, 560.0, 640.0],   # person 0.90
        [404.0, 164.0, 562.0, 642.0],   # duplicate, removed by NMS
        [800.0, 400.0, 1000.0, 600.0],  # vehicle 0.60
        [1100.0, 400.0, 1200.0, 600.0],  # vehicle 0.40
        [100.0, 100.0, 120.0, 120.0],   # bicycle 0.12 (below the 0.15 minimum)
    ],
    dtype=np.float32,
)
RAW_SCORES = np.array(
    [
        [0.90, 0.01, 0.01],
        [0.80, 0.01, 0.01],
        [0.02, 0.01, 0.60],
        [0.02, 0.01, 0.40],
        [0.01, 0.12, 0.01],
    ],
    dtype=np.float32,
)
CLASSES = ["person", "bicycle", "vehicle"]


def build_constant_model(path: str, scores: np.ndarray = RAW_SCORES) -> str:
    """OpenVINO model with the real input/output contract (``boxes``, ``scores``) but constant outputs."""
    import openvino as ov
    from openvino.runtime import opset13 as ops

    images = ops.parameter([1, 3, -1, -1], np.float32, name="images")
    zero = ops.multiply(ops.reduce_mean(images, np.array([1, 2, 3]), keep_dims=True), ops.constant(np.float32(0.0)))
    boxes = ops.add(ops.constant(RAW_BOXES[None]), zero)
    out_scores = ops.add(ops.constant(scores[None]), zero)
    boxes.output(0).get_tensor().set_names({"boxes"})
    out_scores.output(0).get_tensor().set_names({"scores"})
    ov.save_model(ov.Model([boxes, out_scores], [images], "constant-detector"), path)
    return path


@pytest.fixture()
def model_files(tmp_path):
    xml = build_constant_model(str(tmp_path / "src" / "model.xml"))
    return xml, xml[:-4] + ".bin"


def manifest(version: str = "model-0007", classes: list[str] = CLASSES) -> str:
    return json.dumps({"version": version, "class_names": classes, "input_width": 1536, "input_height": 864,
                       "nms_iou_threshold": 0.6, "architecture": "rtmdet-s"})


def upload(client: TestClient, files: tuple[str, str], version: str = "model-0007", key: str | None = ACCESS_KEY,
           classes: list[str] = CLASSES):
    xml, weights = files
    headers = {"X-Access-Key": key} if key else {}
    with open(xml, "rb") as fx, open(weights, "rb") as fb:
        return client.put("/api/v1/model", headers=headers, data={"manifest": manifest(version, classes)},
                          files={"model_xml": ("model.xml", fx), "model_bin": ("model.bin", fb)})


def jpeg(width: int = 1920, height: int = 1080) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((height, width, 3), 127, np.uint8))
    assert ok
    return buf.tobytes()


@pytest.fixture()
def model_dir(tmp_path, monkeypatch):
    path = tmp_path / "models"
    monkeypatch.setenv("MODEL_DIR", str(path))
    from app.config import get_settings

    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture()
def client(model_dir):
    from app.main import app

    with TestClient(app) as c:  # runs the lifespan (loads the installed model)
        yield c


def image_file():
    return {"image": ("a.jpg", io.BytesIO(jpeg()), "image/jpeg")}
