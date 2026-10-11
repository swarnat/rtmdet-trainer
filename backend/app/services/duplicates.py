"""Duplicate check of *empty* images (fixed cameras deliver many near-identical frames).

Only images without objects are compared: labeled negatives (no annotations at all) and open
images whose latest batch test found nothing. For those a plain image comparison is safe; images
with objects are never marked, because a small moved person hardly changes the pixels but is
exactly what the model has to learn.

Comparison on a 128x72 grayscale fingerprint of the thumbnail (top band with the camera's
timestamp overlay ignored, brightness/contrast normalised):

* same view: correlation of a coarse 16x8 version >= VIEW_CORRELATION
* same lighting: mean brightness differs by at most MAX_BRIGHTNESS_DIFF (day vs. night of the same
  scene is useful variety, not a duplicate)
* nothing changed: no 8x6 block differs by more than the setting ``duplicate_max_difference``
  (normalised units; the largest block difference is stored as ``duplicate_score``)

Images are processed labeled first, then by id; the first image of each group stays, the others
get ``duplicate_of``. Every check recomputes all marks, except that images kept on the duplicates
page (``duplicate_keep``) are never marked. Marked duplicates are skipped by training.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session, undefer

from odcore.settings_store import get_setting

from odcore.db import Annotation, AnnotationStatus, Image, ImageSuggestion
from odcore.storage import ObjectStorage

log = logging.getLogger(__name__)

FP_WIDTH, FP_HEIGHT = 128, 72
MASK_TOP = 6                 # rows (of 72) with the timestamp overlay
BLOCK = (6, 8)               # 66x128 -> 11x16 blocks
VIEW_CORRELATION = 0.9
MAX_BRIGHTNESS_DIFF = 20.0   # gray levels


def fingerprint(thumbnail_jpeg: bytes) -> bytes:
    image = cv2.imdecode(np.frombuffer(thumbnail_jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("cannot decode thumbnail")
    return cv2.resize(image, (FP_WIDTH, FP_HEIGHT), interpolation=cv2.INTER_AREA).tobytes()


@dataclass
class _Features:
    mean: float
    view: np.ndarray    # zero-mean, unit-length coarse vector
    detail: np.ndarray  # normalised, slightly blurred image


def _features(fp: bytes) -> _Features:
    g = np.frombuffer(fp, np.uint8).reshape(FP_HEIGHT, FP_WIDTH).astype(np.float32)[MASK_TOP:]
    mean = float(g.mean())
    n = (g - mean) / (float(g.std()) + 1e-6)
    view = cv2.resize(n, (16, 8), interpolation=cv2.INTER_AREA).ravel()
    view = view - view.mean()
    view /= float(np.linalg.norm(view)) + 1e-6
    return _Features(mean, view, cv2.GaussianBlur(n, (3, 3), 0))


def _difference(a: _Features, b: _Features) -> float | None:
    """Largest block difference, or None for another view / other lighting."""
    if abs(a.mean - b.mean) > MAX_BRIGHTNESS_DIFF or float(a.view @ b.view) < VIEW_CORRELATION:
        return None
    h, w = a.detail.shape
    diff = np.abs(a.detail - b.detail).reshape(h // BLOCK[0], BLOCK[0], w // BLOCK[1], BLOCK[1]).mean(axis=(1, 3))
    return float(diff.max())


def find_duplicates(fingerprints: list[tuple[int, bytes]], max_difference: float,
                    keep: set[int] = frozenset()) -> dict[int, tuple[int, float]]:
    """``{image id: (id of the image it duplicates, difference)}``.

    Input order decides which image of a group stays; ids in ``keep`` are never marked (but other
    images can be their duplicates). Each image is compared with the originals only, not chained.
    """
    kept: list[tuple[int, _Features]] = []
    result: dict[int, tuple[int, float]] = {}
    for image_id, fp in fingerprints:
        f = _features(fp)
        match = None
        if image_id not in keep:
            for kid, kf in kept:
                d = _difference(f, kf)
                if d is not None and d <= max_difference:
                    match = (kid, d)
                    break
        if match is None:
            kept.append((image_id, f))
        else:
            result[image_id] = match
    return result


def empty_image_ids(session: Session) -> list[int]:
    """Images without annotations that are labeled (negative) or whose latest batch test found nothing; labeled first."""
    with_annotations = select(Annotation.image_id).distinct()
    rows = session.execute(
        select(Image.id, Image.annotation_status)
        .where(Image.deleted_at.is_(None), Image.id.not_in(with_annotations))
    ).all()
    no_suggestions = {
        image_id for image_id, dets in session.execute(select(ImageSuggestion.image_id, ImageSuggestion.detections_json))
        if not dets
    }
    labeled = sorted(i for i, st in rows if st == AnnotationStatus.labeled)
    unlabeled = sorted(i for i, st in rows if st != AnnotationStatus.labeled and i in no_suggestions)
    return labeled + unlabeled


def ensure_fingerprints(session: Session, storage: ObjectStorage, images: list[Image]) -> tuple[int, int]:
    """Compute missing fingerprints from the thumbnails (images loaded with the fingerprint undeferred)."""
    computed = failed = 0
    for image in images:
        if image.fingerprint is None:
            try:
                key = image.thumbnail_key or image.s3_object_key
                image.fingerprint = fingerprint(storage.get_bytes(storage.settings.bucket_images, key))
                computed += 1
            except Exception as exc:  # one unreadable thumbnail must not stop the check
                log.warning("no fingerprint for image %d: %s", image.id, exc)
                failed += 1
    return computed, failed


def update_duplicates(session: Session, storage: ObjectStorage) -> dict:
    """Recompute ``duplicate_of`` for all images; missing fingerprints are computed from the thumbnails."""
    ids = empty_image_ids(session)
    images = {
        i.id: i for i in session.execute(select(Image).where(Image.id.in_(ids)).options(undefer(Image.fingerprint))).scalars()
    }
    max_difference = float(get_setting(session, "duplicate_max_difference"))
    keep = {i for i, img in images.items() if img.duplicate_keep}
    computed, failed = ensure_fingerprints(session, storage, list(images.values()))
    dups = find_duplicates([(i, images[i].fingerprint) for i in ids if i in images and images[i].fingerprint],
                           max_difference, keep)
    session.flush()  # fingerprints
    session.execute(update(Image).where(Image.duplicate_of.is_not(None)).values(duplicate_of=None, duplicate_score=None),
                    execution_options={"synchronize_session": False})
    for image_id, (original, score) in dups.items():
        session.execute(update(Image).where(Image.id == image_id).values(duplicate_of=original, duplicate_score=round(score, 4)),
                        execution_options={"synchronize_session": False})
    session.commit()
    session.expire_all()
    log.info("duplicate check: %d empty images, %d duplicates (%d fingerprints computed, %d failed)",
             len(ids), len(dups), computed, failed)
    return {"checked": len(ids), "duplicates": len(dups), "fingerprints_computed": computed, "failed": failed}


def clear_marks_for(session: Session, image: Image) -> None:
    """The image got annotations: it is no duplicate any more, and neither are images marked as its copies."""
    image.duplicate_of = image.duplicate_score = None
    session.execute(update(Image).where(Image.duplicate_of == image.id).values(duplicate_of=None, duplicate_score=None),
                    execution_options={"synchronize_session": False})


def keep_images(session: Session, image_ids: list[int]) -> None:
    """Reviewed and kept: no duplicate, now or in later checks."""
    session.execute(
        update(Image).where(Image.id.in_(image_ids)).values(duplicate_keep=True, duplicate_of=None, duplicate_score=None),
        execution_options={"synchronize_session": False},
    )
