"""Ignore regions in the RTMDet training targets (torch only, see ``ignore_head``)."""
from __future__ import annotations

import torch


def cells_in_regions(points: torch.Tensor, regions: torch.Tensor) -> torch.Tensor:
    """Bool mask ``(N,)``: prior centres ``points`` ``(N, 2)`` (x, y) inside any xyxy box of ``regions`` ``(M, 4)``."""
    if not len(regions) or not len(points):
        return torch.zeros(len(points), dtype=torch.bool, device=points.device)
    x, y = points[:, 0:1], points[:, 1:2]
    inside = (x >= regions[None, :, 0]) & (x <= regions[None, :, 2]) & (y >= regions[None, :, 1]) & (y <= regions[None, :, 3])
    return inside.any(dim=1)


def mute_background(label_weights: torch.Tensor, labels: torch.Tensor, points: torch.Tensor, regions: torch.Tensor,
                    num_classes: int) -> torch.Tensor:
    """Classification weights with the background cells inside ``regions`` set to 0 (cells assigned to a box stay)."""
    muted = cells_in_regions(points, regions) & (labels == num_classes)
    return label_weights.masked_fill(muted, 0.0)
