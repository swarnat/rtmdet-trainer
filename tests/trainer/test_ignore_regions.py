"""Ignore regions in the training targets (the head itself needs MMDetection and is covered by the trainer image)."""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from trainer.rtmdet.ignore_regions import cells_in_regions, mute_background  # noqa: E402

NUM_CLASSES = 3


def test_cells_in_regions():
    points = torch.tensor([[10.0, 10.0], [50.0, 50.0], [95.0, 20.0], [200.0, 200.0]])
    regions = torch.tensor([[0.0, 0.0, 20.0, 20.0], [90.0, 0.0, 100.0, 30.0]])
    assert cells_in_regions(points, regions).tolist() == [True, False, True, False]
    assert not cells_in_regions(points, torch.zeros((0, 4))).any()


def test_only_background_cells_are_muted():
    points = torch.tensor([[10.0, 10.0], [12.0, 12.0], [14.0, 14.0], [200.0, 200.0]])
    labels = torch.tensor([NUM_CLASSES, 1, NUM_CLASSES, NUM_CLASSES])  # cell 1 belongs to a real box
    weights = torch.ones(4)
    out = mute_background(weights, labels, points, torch.tensor([[0.0, 0.0, 20.0, 20.0]]), NUM_CLASSES)
    assert out.tolist() == [0.0, 1.0, 0.0, 1.0]
    assert weights.tolist() == [1.0] * 4  # input untouched
