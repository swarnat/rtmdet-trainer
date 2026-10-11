"""Camera groups for the quick review of open images without suggestions."""
from __future__ import annotations

import numpy as np

from app.services.camera_groups import build_groups

from test_duplicates import fp, scene


def test_groups_by_view_chain_order_and_comparison_images():
    a = scene(1).astype(np.int16)
    b = scene(5).astype(np.int16)
    person = a.copy()
    person[40:52, 60:66] = 255
    candidates = [
        (1, fp(a + 2)),        # camera A
        (2, fp(b)),            # camera B
        (3, fp(a - 60)),       # camera A at night: same group, other lighting
        (4, fp(person)),       # camera A with something in it
        (5, fp(a - 55)),
    ]
    references = [(9, fp(a))]  # known-empty image of camera A (daylight)
    groups = build_groups(candidates, references)
    order = [[e["id"] for e in g["images"]] for g in groups]
    # the two night images are equal after brightness normalisation: their order is arbitrary
    assert order[0][:2] == [1, 4] and sorted(order[0][2:]) == [3, 5] and order[1] == [2]
    by_id = {e["id"]: e for g in groups for e in g["images"]}
    # daylight images are compared with the negative, night images with their predecessor
    assert (by_id[1]["compare_with"], by_id[1]["compare_kind"]) == (9, "negative")
    assert (by_id[4]["compare_with"], by_id[4]["compare_kind"]) == (9, "negative")
    first_night, second_night = order[0][2:]
    assert (by_id[second_night]["compare_with"], by_id[second_night]["compare_kind"]) == (first_night, "previous")
    assert by_id[2]["compare_with"] is None


def test_groups_without_open_images_are_dropped():
    assert build_groups([], [(9, fp(scene(1)))]) == []


def test_average_linkage_does_not_chain_through_one_bridge_image():
    from app.services.camera_groups import cluster

    def unit(v):
        v = np.asarray(v, dtype=float)
        return v / np.linalg.norm(v)
    a, b = np.eye(3)[0], np.eye(3)[1]
    vectors = np.stack([unit(a), unit(a + 0.05 * b), unit(a + b),  # the last one resembles both cameras a little
                        unit(b), unit(b + 0.05 * a)])
    # the bridge image is similar enough (0.71) to both cameras; single linkage would join everything
    groups = sorted(sorted(c) for c in cluster(vectors, 0.6))
    assert len(groups) == 2 and {0, 1} <= set(groups[0]) and {3, 4} <= set(groups[-1])


def test_low_contrast_night_image_stays_with_its_camera():
    a = scene(1).astype(np.float32)
    night = (a - a.mean()) * 0.25 + 30  # dark, little contrast
    groups = build_groups([(1, fp(a)), (2, fp(night)), (3, fp(scene(9)))], [])
    assert sorted(sorted(e["id"] for e in g["images"]) for g in groups) == [[1, 2], [3]]


def test_metadata_separates_devices_and_joins_day_and_night():
    a = scene(1).astype(np.float32)
    night = (a - a.mean()) * 0.25 + 30
    candidates = [(1, fp(a)), (2, fp(a + 1)), (3, fp(night))]
    # same picture, but image 2 comes from another device: never grouped with 1
    keys = {1: "AXIS Q3536-LVE · AAA", 2: "AXIS Q3536-LVE · BBB", 3: "AXIS Q3536-LVE · AAA"}
    groups = build_groups(candidates, [], keys)
    assert sorted((g["camera"], sorted(e["id"] for e in g["images"])) for g in groups) == [
        ("AXIS Q3536-LVE · AAA", [1, 3]), ("AXIS Q3536-LVE · BBB", [2])]


def test_metadata_grouping_can_be_switched_off(session_factory):
    from odcore.db import Image, ImageSuggestion
    from odcore.settings_store import set_setting

    from app.services.camera_groups import open_without_suggestions_groups

    a = scene(1).astype(np.int16)
    with session_factory() as s:
        for i, key in ((1, "AXIS Q3536-LVE · AAA"), (2, "AXIS Q3536-LVE · BBB")):
            s.add(Image(id=i, s3_object_key=f"images/{i}.jpg", sha256=f"{i:064d}", content_type="image/jpeg", size_bytes=1,
                        width=1920, height=1080, annotation_status="unlabeled", fingerprint=fp(a + i), camera_key=key))
        # image 3: never batch-tested -> not reviewed, only counted
        s.add(Image(id=3, s3_object_key="images/3.jpg", sha256=f"{3:064d}", content_type="image/jpeg", size_bytes=1,
                    width=1920, height=1080, annotation_status="unlabeled", fingerprint=fp(a), camera_key=""))
        s.flush()
        for i in (1, 2):  # batch test found nothing
            s.add(ImageSuggestion(image_id=i, model_version="m", input_width=1536, input_height=864, confidence=0.25,
                                  detections_json=[]))
        s.commit()
        groups, untested = open_without_suggestions_groups(s, None)
        assert (len(groups), untested) == (2, 1)   # different devices
        set_setting(s, "camera_groups_use_metadata", False)
        s.commit()
        groups, _ = open_without_suggestions_groups(s, None)
        assert [(g["camera"], len(g["images"])) for g in groups] == [("", 2)]  # same picture: one group
