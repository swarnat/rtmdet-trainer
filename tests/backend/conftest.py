"""Backend test fixtures. The API is tested with a real OpenVINO model (built
in-process) and an in-memory SQLite database instead of PostgreSQL/S3."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:3900")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("MODEL_CACHE_DIR", "/tmp/od-test-cache")

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from odcore.db import Base

# Fixed raw model outputs in model-input pixels for a 1536x864 input
RAW_BOXES = np.array(
    [
        [400.0, 160.0, 560.0, 640.0],   # person, conf 0.9
        [404.0, 164.0, 562.0, 642.0],   # overlapping duplicate (removed by NMS)
        [800.0, 400.0, 1000.0, 600.0],  # vehicle, conf 0.6
        [100.0, 100.0, 120.0, 120.0],   # bicycle, conf 0.1 (below threshold)
    ],
    dtype=np.float32,
)
RAW_SCORES = np.array(
    [
        [0.90, 0.01, 0.01],
        [0.80, 0.01, 0.01],
        [0.02, 0.01, 0.60],
        [0.01, 0.10, 0.01],
    ],
    dtype=np.float32,
)


def build_constant_model(path: str) -> str:
    """OpenVINO model with the real input/output contract but constant outputs."""
    import openvino as ov
    from openvino.runtime import opset13 as ops

    images = ops.parameter([1, 3, -1, -1], np.float32, name="images")
    zero = ops.multiply(ops.reduce_mean(images, np.array([1, 2, 3]), keep_dims=True), ops.constant(np.float32(0.0)))
    boxes = ops.add(ops.constant(RAW_BOXES[None]), zero)
    scores = ops.add(ops.constant(RAW_SCORES[None]), zero)
    boxes.output(0).get_tensor().set_names({"boxes"})
    scores.output(0).get_tensor().set_names({"scores"})
    model = ov.Model([boxes, scores], [images], "constant-detector")
    ov.save_model(model, path)
    return path


@pytest.fixture()
def constant_model_xml(tmp_path) -> str:
    return build_constant_model(str(tmp_path / "model.xml"))


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
