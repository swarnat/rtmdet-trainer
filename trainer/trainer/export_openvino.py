"""Convert the ONNX model to OpenVINO IR and verify it against PyTorch."""
from __future__ import annotations

import logging
import os

import numpy as np
import torch

log = logging.getLogger(__name__)


def export_openvino(onnx_path: str, out_dir: str) -> str:
    """Write ``model.xml``/``model.bin`` (FP32, dynamic H/W; the API reshapes to a static shape)."""
    import openvino as ov

    os.makedirs(out_dir, exist_ok=True)
    model = ov.convert_model(onnx_path)
    xml_path = os.path.join(out_dir, "model.xml")
    ov.save_model(model, xml_path, compress_to_fp16=False)
    log.info("saved OpenVINO IR to %s", xml_path)
    return xml_path


def verify_openvino(wrapper: torch.nn.Module, xml_path: str, sizes: list[tuple[int, int]], atol: float = 1e-2) -> dict:
    """Compare OpenVINO (statically reshaped per size) with PyTorch on random input."""
    import openvino as ov

    core = ov.Core()
    report = {}
    rng = np.random.default_rng(0)
    for w, h in sizes:
        model = core.read_model(xml_path)
        model.reshape({model.inputs[0].get_any_name(): [1, 3, h, w]})
        compiled = core.compile_model(model, "CPU")
        x = rng.uniform(0, 255, size=(1, 3, h, w)).astype(np.float32)
        out = compiled({0: x})
        ov_scores = out[compiled.output("scores")]
        ov_boxes = out[compiled.output("boxes")]
        with torch.no_grad():
            pt_boxes, pt_scores = wrapper(torch.from_numpy(x))
        score_diff = float(np.abs(ov_scores - pt_scores.numpy()).max())
        box_diff = float(np.abs(ov_boxes - pt_boxes.numpy()).max())
        report[f"{w}x{h}"] = {"max_score_diff": score_diff, "max_box_diff_px": box_diff}
        log.info("OpenVINO vs PyTorch at %dx%d: max score diff %.2e, max box diff %.3f px", w, h, score_diff, box_diff)
        if score_diff > atol:
            raise RuntimeError(f"OpenVINO output deviates from PyTorch at {w}x{h} (score diff {score_diff})")
    return report
