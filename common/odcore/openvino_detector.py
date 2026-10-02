"""OpenVINO CPU detector used by the API and by the trainer's evaluation.

The exported model takes a ``1x3xHxW`` float32 BGR tensor (0..255, letterboxed)
and returns ``boxes`` (``1xNx4`` xyxy in input pixels) and ``scores``
(``1xNxC`` sigmoid scores). Normalisation is part of the model graph.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from .geometry import Detection, letterbox, postprocess, to_model_input, validate_input_size


@dataclass
class DetectionResult:
    detections: list[Detection]
    inference_ms: float


class OpenVinoDetector:
    """A model compiled for one static input shape."""

    def __init__(self, core, xml_path: str, input_width: int, input_height: int, device: str = "CPU",
                 num_streams: int | None = None):
        validate_input_size(input_width, input_height)
        model = core.read_model(xml_path)
        model.reshape({model.inputs[0].get_any_name(): [1, 3, input_height, input_width]})
        config = {"PERFORMANCE_HINT": "LATENCY"}
        if num_streams:
            config = {"PERFORMANCE_HINT": "THROUGHPUT", "NUM_STREAMS": str(num_streams)}
        self.compiled = core.compile_model(model, device, config)
        self.input_width = input_width
        self.input_height = input_height
        self._boxes_out = self.compiled.output("boxes")
        self._scores_out = self.compiled.output("scores")
        self._local = threading.local()

    def _request(self):
        req = getattr(self._local, "request", None)
        if req is None:
            req = self.compiled.create_infer_request()
            self._local.request = req
        return req

    def infer_raw(self, image: np.ndarray):
        canvas, info = letterbox(image, self.input_width, self.input_height)
        tensor = to_model_input(canvas)
        req = self._request()
        req.infer({0: tensor})
        boxes = req.get_tensor(self._boxes_out).data[0].copy()
        scores = req.get_tensor(self._scores_out).data[0].copy()
        return boxes, scores, info

    def detect(self, image: np.ndarray, score_threshold: float, iou_threshold: float) -> DetectionResult:
        start = time.perf_counter()
        boxes, scores, info = self.infer_raw(image)
        detections = postprocess(boxes, scores, info, score_threshold, iou_threshold)
        return DetectionResult(detections, (time.perf_counter() - start) * 1000.0)
