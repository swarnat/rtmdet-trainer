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


def test_neighbours_stay_within_split(session_factory):
    from odcore.db import DatasetSplit

    from app.db.repositories.images import list_images, neighbour_ids

    with session_factory() as s:
        imgs = [make_image(s, sha=str(i) * 64) for i in range(4)]
        for img, split in zip(imgs, [DatasetSplit.train, DatasetSplit.validation, DatasetSplit.train, None]):
            img.dataset_split = split
        s.commit()
        ids = [i.id for i in imgs]
        assert neighbour_ids(s, ids[0], None, DatasetSplit.train) == (None, ids[2])
        assert neighbour_ids(s, ids[1], None, DatasetSplit.validation) == (None, None)
        assert neighbour_ids(s, ids[0], None) == (None, ids[1])
        total, items = list_images(s, split=DatasetSplit.validation)
        assert total == 1 and items[0].id == ids[1]


def test_last_upload_session(session_factory):
    from datetime import datetime, timedelta, timezone

    from app.db.repositories.images import last_upload_ids

    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    offsets = {1: 0, 2: 5, 3: 300, 4: 310, 5: 335}  # minutes: two sessions, the second one with < 30 min pauses
    with session_factory() as s:
        for i, m in offsets.items():
            s.add(Image(id=i, s3_object_key=f"images/{i}.jpg", sha256=f"{i:064d}", content_type="image/jpeg",
                        size_bytes=1, width=10, height=10, created_at=t0 + timedelta(minutes=m)))
        s.commit()
        assert sorted(last_upload_ids(s)) == [3, 4, 5]
        s.get(Image, 5).deleted_at = t0
        s.commit()
        assert sorted(last_upload_ids(s)) == [3, 4]


def test_split_chosen_before_labeling_is_kept(session_factory):
    from odcore.db import DatasetSplit

    with session_factory() as s:
        img = make_image(s, sha="c" * 64)
        img.dataset_split = DatasetSplit.validation  # chosen in the UI before the first save (e.g. a real intrusion)
        s.commit()
        replace_annotations(s, img, [], mark_labeled=True)
        assert img.dataset_split == DatasetSplit.validation


def test_ignore_region_and_reflection_are_saved(session_factory):
    with session_factory() as s:
        img = make_image(s, sha="c" * 64)
        items = [
            AnnotationIn.model_validate({"class": "person", "x1": 10, "y1": 10, "x2": 90, "y2": 200, "reflected": True}),
            AnnotationIn.model_validate({"class": "person", "x1": 300, "y1": 10, "x2": 400, "y2": 200, "type": "ignore",
                                         "source_confidence": 0.7}),
            AnnotationIn.model_validate({"class": "person", "x1": 500, "y1": 10, "x2": 600, "y2": 200}),
        ]
        img = replace_annotations(s, img, items, mark_labeled=True)
        assert [(a.type, a.reflected) for a in img.annotations] == [("positive", True), ("ignore", False), ("positive", False)]
        assert img.annotations[1].source_confidence is None  # only hard negatives keep the false detection's confidence


def test_unknown_annotation_type_is_rejected():
    with pytest.raises(ValueError):
        AnnotationIn.model_validate({"class": "person", "x1": 0, "y1": 0, "x2": 50, "y2": 50, "type": "maybe"})
