"""Camera groups for the quick review of open images on which a batch test found nothing.

Only *tested* images are reviewed: an open image without any batch-test result is unknown territory and
belongs into a batch test first (the number of such images is reported).

Fixed cameras: images of the same view are grouped so they can be stepped through and blink-compared.
Grouping uses an *edge* map of the duplicate-check fingerprint (rails, masts and buildings stay the same by
day, at night and in infrared mode, unlike brightness patterns that change with haze, sun and moved trains)
and average-linkage clustering (a group's members must be similar on average, so one odd image cannot
chain two cameras together).

The camera identity from the metadata (EXIF serial number, see camera_meta) is a hard boundary: images
of different devices are never grouped. Within one device the visual threshold is low (day, night and
infrared differ a lot, other PTZ presets/encoder channels hardly resemble each other); within a camera
type without serial a little higher; without any metadata the plain visual threshold. Within a group each
image follows the one most similar to it (greedy chain), and each image gets a comparison image: the
most similar known-empty image of the same view (labeled negative, similar lighting) or else its
predecessor in the chain. Whatever shows up when blinking is a candidate object.
"""
from __future__ import annotations

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from odcore.db import Annotation, AnnotationStatus, Image, ImageSuggestion
from odcore.settings_store import get_setting
from odcore.storage import ObjectStorage

from app.services.camera_meta import HEADER_BYTES, SERIAL_SEPARATOR, camera_key
from app.services.duplicates import MAX_BRIGHTNESS_DIFF, _features, ensure_fingerprints

# average edge-map correlation for merging groups, by what the metadata says (checked on real data):
CAMERA_LINKAGE = 0.5          # no metadata
CAMERA_LINKAGE_TYPE = 0.3     # same camera type, no serial (e.g. "CamTim": several devices)
CAMERA_LINKAGE_DEVICE = 0.2   # same device (serial number)
TOP_MASK = 6  # rows (of 72) with the timestamp overlay


def _edge_view(fp: bytes) -> np.ndarray:
    """Zero-mean unit vector of the blurred, contrast-normalised gradient magnitude (32x16)."""
    g = np.frombuffer(fp, np.uint8).reshape(72, 128).astype(np.float32)[TOP_MASK:]
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    m = np.sqrt(gx * gx + gy * gy)
    m = np.minimum(m / (np.percentile(m, 95) + 1e-6), 1.0)  # independent of contrast (night, IR)
    v = cv2.resize(cv2.GaussianBlur(m, (5, 5), 0), (32, 16), interpolation=cv2.INTER_AREA).ravel()
    v = v - v.mean()
    return v / (float(np.linalg.norm(v)) + 1e-6)


def cluster(vectors: np.ndarray, threshold: float) -> list[list[int]]:
    """Average-linkage agglomerative clustering on cosine similarity; returns lists of row indices."""
    n = len(vectors)
    sim = vectors @ vectors.T
    np.fill_diagonal(sim, -np.inf)
    size = np.ones(n)
    members = [[i] for i in range(n)]
    while n > 1:
        a, b = divmod(int(np.argmax(sim)), len(sim))
        if sim[a, b] < threshold:
            break
        row = (sim[a] * size[a] + sim[b] * size[b]) / (size[a] + size[b])
        sim[a], sim[:, a] = row, row
        sim[a, a] = -np.inf
        sim[b], sim[:, b] = -np.inf, -np.inf
        size[a] += size[b]
        members[a] += members[b]
        members[b] = []
    return [m for m in members if m]


def _distance(a, b) -> float:
    return float(np.abs(a.detail - b.detail).mean())


def _threshold(key: str) -> float:
    if not key:
        return CAMERA_LINKAGE
    return CAMERA_LINKAGE_DEVICE if SERIAL_SEPARATOR in key else CAMERA_LINKAGE_TYPE


def build_groups(candidates: list[tuple[int, bytes]], references: list[tuple[int, bytes]],
                 keys: dict[int, str] | None = None) -> list[dict]:
    """``[{"camera", "images": [{"id", "compare_with", "compare_kind"}]}]``, largest group first.

    ``candidates``: images to review; ``references``: known-empty images (only used for comparison);
    ``keys``: camera identity per image (missing = unknown).
    """
    items = candidates + references
    if not items:
        return []
    keys = keys or {}
    feats = {i: _features(fp) for i, fp in items}
    ref_ids = {i for i, _ in references}
    by_key: dict[str, list[tuple[int, bytes]]] = {}
    for i, fp in items:
        by_key.setdefault(keys.get(i) or "", []).append((i, fp))
    clusters: list[tuple[str, list[int]]] = []
    for key, members in by_key.items():
        edges = np.stack([_edge_view(fp) for _, fp in members])
        clusters += [(key, [members[k][0] for k in c]) for c in cluster(edges, _threshold(key))]

    groups = []
    for key, c in clusters:
        todo = [i for i in c if i not in ref_ids]
        if not todo:
            continue
        refs = [i for i in c if i in ref_ids]
        # greedy chain: start with the lowest id, always continue with the most similar remaining image
        order = [min(todo)]
        rest = set(todo) - {order[0]}
        while rest:
            nxt = min(rest, key=lambda j: (_distance(feats[order[-1]], feats[j]), j))
            order.append(nxt)
            rest.remove(nxt)
        images = []
        for pos, i in enumerate(order):
            similar = [r for r in refs if abs(feats[r].mean - feats[i].mean) <= MAX_BRIGHTNESS_DIFF]
            if similar:
                ref = min(similar, key=lambda r: (_distance(feats[i], feats[r]), r))
                images.append({"id": i, "compare_with": ref, "compare_kind": "negative"})
            elif pos:
                images.append({"id": i, "compare_with": order[pos - 1], "compare_kind": "previous"})
            else:
                images.append({"id": i, "compare_with": None, "compare_kind": None})
        groups.append({"camera": key, "images": images})
    return sorted(groups, key=lambda g: (-len(g["images"]), g["images"][0]["id"]))


def tested_empty_open_ids(session: Session) -> tuple[list[int], int]:
    """Open images whose latest batch test found nothing, and the number of open images never tested."""
    results = dict(session.execute(select(ImageSuggestion.image_id, ImageSuggestion.detections_json)).all())
    open_all = session.execute(
        select(Image.id).where(Image.deleted_at.is_(None), Image.annotation_status == AnnotationStatus.unlabeled)
    ).scalars().all()
    tested_empty = [i for i in open_all if i in results and not results[i]]
    untested = sum(1 for i in open_all if i not in results)
    return tested_empty, untested


def open_without_suggestions_groups(session: Session, storage: ObjectStorage) -> tuple[list[dict], int]:
    """Groups of the tested open images without suggestions, and the number of untested open images."""
    with_annotations = select(Annotation.image_id).distinct()
    open_ids, untested = tested_empty_open_ids(session)
    negative_ids = list(session.execute(
        select(Image.id).where(Image.deleted_at.is_(None), Image.annotation_status == AnnotationStatus.labeled,
                               Image.id.not_in(with_annotations))
    ).scalars())
    images = {
        i.id: i for i in session.execute(
            select(Image).where(Image.id.in_(open_ids + negative_ids)).options(undefer(Image.fingerprint))
        ).scalars()
    }
    ensure_fingerprints(session, storage, list(images.values()))
    keys = None
    if get_setting(session, "camera_groups_use_metadata"):
        ensure_camera_keys(storage, list(images.values()))
        keys = {i: img.camera_key or "" for i, img in images.items()}
    session.commit()
    fp = lambda ids: [(i, images[i].fingerprint) for i in sorted(ids) if images[i].fingerprint]  # noqa: E731
    return build_groups(fp(open_ids), fp(negative_ids), keys), untested


def ensure_camera_keys(storage: ObjectStorage, images: list[Image]) -> None:
    """Read the metadata of images uploaded before camera keys were stored (once per image)."""
    for image in images:
        if image.camera_key is None:
            try:
                data = storage.get_bytes(storage.settings.bucket_images, image.s3_object_key)
                image.camera_key = camera_key(data[:HEADER_BYTES])
            except Exception:  # unreadable file: treat as unknown, try again next time
                continue
