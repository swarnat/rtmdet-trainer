"""Annotation saving: negatives, validation, persistent splits."""
from __future__ import annotations

import pytest

from odcore.db import AnnotationStatus, Image
from odcore.splits import assign_split

from app.schemas.annotation import AnnotationIn
from app.services.annotation import AnnotationValidationError, replace_annotations


def make_image(session, sha="a" * 64):
    img = Image(s3_object_key=f"images/{sha}.jpg", sha256=sha, content_type="image/jpeg", size_bytes=1,
                width=1920, height=1080)
    session.add(img)
    session.commit()
    return img


def test_empty_annotation_list_marks_negative_image(session_factory):
    with session_factory() as s:
        img = make_image(s)
        assert img.annotation_status == AnnotationStatus.unlabeled
        img = replace_annotations(s, img, [], mark_labeled=True)
        assert img.annotation_status == AnnotationStatus.labeled
        assert img.annotations == []
        assert img.dataset_split is not None


def test_boxes_are_normalised_and_clipped(session_factory):
    with session_factory() as s:
        img = make_image(s)
        items = [AnnotationIn.model_validate({"class": "person", "x1": 600, "y1": 900, "x2": 400, "y2": -20})]
        img = replace_annotations(s, img, items, mark_labeled=True)
        a = img.annotations[0]
        assert (a.class_name, a.x1, a.y1, a.x2, a.y2) == ("person", 400, 0, 600, 900)


def test_degenerate_box_is_rejected(session_factory):
    with session_factory() as s:
        img = make_image(s)
        items = [AnnotationIn.model_validate({"class": "vehicle", "x1": 10, "y1": 10, "x2": 10.2, "y2": 50})]
        with pytest.raises(AnnotationValidationError):
            replace_annotations(s, img, items, mark_labeled=True)


def test_split_is_not_rerolled(session_factory):
    with session_factory() as s:
        img = make_image(s, sha="b" * 64)
        replace_annotations(s, img, [], mark_labeled=True)
        first = img.dataset_split
        # flip it manually, re-saving must keep the persisted value
        img.dataset_split = type(first)("validation" if first.value == "train" else "train")
        s.commit()
        replace_annotations(s, img, [], mark_labeled=True)
        assert img.dataset_split != first


def test_assign_split_deterministic_and_ratio():
    shas = [f"{i:064x}" for i in range(4000)]
    splits = [assign_split(sha, 0.15) for sha in shas]
    assert splits == [assign_split(sha, 0.15) for sha in shas]
    ratio = splits.count("validation") / len(splits)
    assert 0.12 < ratio < 0.18
