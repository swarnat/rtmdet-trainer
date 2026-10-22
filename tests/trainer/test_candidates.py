"""Candidate search: picking the proposals of one image (the OWLv2 model itself is not needed here)."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import numpy as np
import pytest

from odcore.db import Annotation
from trainer.candidates import select_proposals, to_image_boxes

W, H = 1920, 1080
PROMPTS = ["excavator", "digger"]


def propose(boxes, scores, labels, annotations=(), min_score=0.1):
    return select_proposals(np.array(boxes, dtype=float), np.array(scores), labels, PROMPTS, W, H, list(annotations), "excavator", min_score)


def test_boxes_are_clipped_to_the_image():
    # OWLv2 boxes are relative to the padded square: parts below the image (square side = width) are cut off
    out = to_image_boxes(np.array([[1800, 1000, 2000, 1500], [-5, -5, 40, 40]]), W, H)
    assert out.tolist() == [[1800, 1000, 1920, 1080], [0, 0, 40, 40]]


def test_threshold_tiny_boxes_and_duplicates_across_queries():
    out = propose(
        boxes=[[100, 100, 300, 300], [105, 100, 305, 300], [600, 600, 900, 800], [500, 500, 504, 504], [1000, 100, 1200, 300]],
        scores=[0.4, 0.6, 0.3, 0.9, 0.05],   # the 2nd is the same object as the 1st, found by the other query
        labels=[0, 1, 0, 0, 0],
    )
    assert [(p.prompt, round(p.score, 2)) for p in out] == [("digger", 0.6), ("excavator", 0.3)]  # tiny box and 0.05 dropped


def test_known_objects_hard_negatives_and_ignore_regions_are_not_proposed_again():
    annotations = [
        Annotation(class_name="excavator", type="positive", x1=100, y1=100, x2=300, y2=300),      # already annotated
        Annotation(class_name="excavator", type="hard_negative", x1=600, y1=100, x2=800, y2=300),  # known non-object
        Annotation(class_name="person", type="ignore", x1=1000, y1=100, x2=1300, y2=400),         # ignore: any class
        Annotation(class_name="vehicle", type="positive", x1=1500, y1=600, x2=1800, y2=900),      # other class: a split candidate
        Annotation(class_name="person", type="positive", x1=200, y1=700, x2=400, y2=900),         # other class: stays
    ]
    boxes = [[100, 100, 300, 300], [600, 100, 800, 300], [1050, 150, 1250, 350], [1500, 600, 1800, 900], [210, 700, 400, 900], [50, 50, 90, 90]]
    out = propose(boxes, [0.9] * 6, [0] * 6, annotations=annotations)
    assert [(round(p.x1), round(p.y1)) for p in out] == [(1500, 600), (210, 700), (50, 50)]


def test_nothing_found():
    assert propose(np.zeros((0, 4)), [], []) == []
    assert propose([[0, 0, 100, 100]], [0.05], [0]) == []


# -- search by example boxes -----------------------------------------------------------------------------------
from trainer.candidates import example_scores, pick_example_box, rank_example_matches  # noqa: E402


def test_example_scores_separate_matches_from_other_objects():
    scores = example_scores(np.array([15.0, 10.0, 7.0, 4.3, 0.0, -20.0]))
    assert scores[0] > 0.95 and scores[1] > 0.8 and scores[2] == pytest.approx(0.5)
    assert scores[3] < 0.25 and scores[4] < 0.05 and scores[5] == pytest.approx(0.0, abs=1e-4)
    assert np.all(np.diff(scores) < 0)  # monotonic: the ranking by logit is kept


def test_example_box_must_fit_a_predicted_box():
    predicted = np.array([[0, 0, 50, 50], [98, 100, 302, 398], [500, 500, 600, 600]])
    assert pick_example_box((100, 100, 300, 400), predicted) == 1
    assert pick_example_box((700, 700, 800, 800), predicted) is None          # nothing there: the example is not usable
    assert pick_example_box((100, 100, 300, 400), np.zeros((0, 4))) is None


def test_example_matches_only_keep_object_like_boxes_and_the_best_example():
    # junk boxes have the highest logits but no objectness (what a raw ranking would show first)
    logits = np.array([[9.0, 1.0], [14.0, 2.0], [3.0, 11.0], [2.0, 1.0]])
    objectness = np.array([0.0, 0.5, 0.6, 0.02])
    idx, scores, best = rank_example_matches(logits, objectness)
    assert idx.tolist() == [1, 2] and best.tolist() == [0, 1]
    assert scores[0] > scores[1] > 0.5
    idx, scores, best = rank_example_matches(logits, np.zeros(4))
    assert len(idx) == len(scores) == len(best) == 0
