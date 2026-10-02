"""Export an RTMDet detector to ONNX with decoding inside the graph.

Graph contract (also used by ``odcore.openvino_detector``):

* input  ``images``: ``1x3xHxW`` float32, BGR, 0..255, letterboxed (H, W dynamic)
* output ``boxes``:  ``1xNx4`` xyxy in input pixels
* output ``scores``: ``1xNxC`` sigmoid class scores

Normalisation, prior generation and distance->box decoding are part of the
graph; NMS is done on the host (numpy), which keeps the graph portable and
lets OpenVINO compile it for any static input shape.
"""
from __future__ import annotations

import logging

import torch
from torch import nn

log = logging.getLogger(__name__)

OPSET = 17


class RTMDetDeployWrapper(nn.Module):
    def __init__(self, detector: nn.Module, class_groups: list[list[int]] | None = None):
        super().__init__()
        self.detector = detector
        dp = detector.data_preprocessor
        self.register_buffer("mean", torch.as_tensor(dp.mean, dtype=torch.float32).view(1, 3, 1, 1).clone())
        self.register_buffer("std", torch.as_tensor(dp.std, dtype=torch.float32).view(1, 3, 1, 1).clone())
        gen = detector.bbox_head.prior_generator
        if any(float(o) != 0.0 for o in [getattr(gen, "offset", 0.0)]):
            raise ValueError("only zero-offset point priors are supported")
        self.strides = [int(s[0]) for s in gen.strides]
        # Optional class merging, e.g. COCO (car, motorcycle, bus, truck) -> vehicle
        self.class_groups = class_groups

    def forward(self, images: torch.Tensor):
        x = (images - self.mean) / self.std
        feats = self.detector.extract_feat(x)
        cls_scores, bbox_preds = self.detector.bbox_head(feats)
        all_boxes, all_scores = [], []
        for cls, reg, stride in zip(cls_scores, bbox_preds, self.strides):
            n, c, h, w = cls.shape
            xs = torch.arange(w, device=images.device, dtype=torch.float32) * stride
            ys = torch.arange(h, device=images.device, dtype=torch.float32) * stride
            px = xs.view(1, -1).expand(h, w).reshape(1, -1)
            py = ys.view(-1, 1).expand(h, w).reshape(1, -1)
            # bbox_preds are distances (left, top, right, bottom) already scaled by stride
            d = reg.permute(0, 2, 3, 1).reshape(n, -1, 4)
            boxes = torch.stack([px - d[..., 0], py - d[..., 1], px + d[..., 2], py + d[..., 3]], dim=-1)
            all_boxes.append(boxes)
            all_scores.append(cls.permute(0, 2, 3, 1).reshape(n, -1, c).sigmoid())
        boxes = torch.cat(all_boxes, dim=1)
        scores = torch.cat(all_scores, dim=1)
        if self.class_groups is not None:
            scores = torch.stack([scores[..., idx].amax(dim=-1) for idx in self.class_groups], dim=-1)
        return boxes, scores


def build_detector(cfg, checkpoint: str):
    """Instantiate the detector from an mmengine config and load weights (CPU, eval)."""
    from mmdet.apis import init_detector

    model = init_detector(cfg, checkpoint, device="cpu")
    model.eval()
    return model


def export_onnx(wrapper: RTMDetDeployWrapper, path: str, input_width: int, input_height: int) -> None:
    wrapper.eval()
    dummy = torch.full((1, 3, input_height, input_width), 114.0)
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            dummy,
            path,
            opset_version=OPSET,
            input_names=["images"],
            output_names=["boxes", "scores"],
            dynamic_axes={"images": {2: "height", 3: "width"}, "boxes": {1: "num_priors"}, "scores": {1: "num_priors"}},
            do_constant_folding=True,
        )
    import onnx

    model = onnx.load(path)
    onnx.checker.check_model(model)
    log.info("exported ONNX model to %s (opset %d)", path, OPSET)
