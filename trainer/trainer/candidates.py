"""Candidate search: propose boxes of a (new) class in the existing images with OWLv2 (open-vocabulary detector).

Two ways to say what to look for (``CandidateSearch.mode``):

* ``text``: text queries (e.g. "excavator").
* ``examples``: boxes of existing annotations. Each example image runs through the model once and the
  predicted box that best fits the annotated box (IoU >= 0.5) supplies the query embedding - the object keeps its
  context, unlike a tight crop, which OWLv2 pads to a square and then embeds the wrong box for flat objects.

The queries are matched against every image of the chosen scope. Boxes above ``min_score`` are stored as
candidates (``odcore.db.Candidate``) while the search runs; the API shows them as crops and turns accepted ones into
annotations. Nothing here changes annotations.

OWLv2 pads an image to a square (bottom/right) before it scales it to 960x960, so its boxes are relative to
that square: ``to_image_boxes`` converts them to original pixels.
"""
from __future__ import annotations

import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from odcore.db import Annotation, AnnotationStatus, BatchStatus, Candidate, CandidateSearch, Image, utcnow
from odcore.geometry import IGNORE_COVERAGE, box_ioa, box_iou, decode_image, nms

from .config import get_settings
from .db import session_factory, storage

log = logging.getLogger(__name__)

BATCH_SIZE = 4
# examples: OWLv2's objectness head separates real objects from the thousands of other boxes. Image-conditioned logits
# alone rank meaningless boxes first (objectness ~0), so boxes below this are dropped (a calibration on one test image:
# junk <= 0.03, real objects 0.45-0.66)
MIN_OBJECTNESS = 0.1
EXAMPLE_IOU = 0.5       # the predicted box used as example must fit the annotated box
# example logits of matching objects are ~10-15, other objects ~0-4 (one test image): shown as a 0-1 score
LOGIT_MIDPOINT, LOGIT_SCALE = 7.0, 2.0
MIN_BOX_PX = 8          # smaller boxes are noise
NMS_IOU = 0.5           # several queries (or overlapping detections) of one object: keep the best
KNOWN_IOU = 0.5         # a candidate on a box the image already has is not new


@dataclass(frozen=True)
class Proposal:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    prompt: str


def to_image_boxes(boxes: np.ndarray, width: int, height: int) -> np.ndarray:
    """Clip boxes (xyxy, padded-square pixels = original pixels) to the image."""
    boxes = np.asarray(boxes, dtype=np.float64).reshape(-1, 4).copy()
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, width)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, height)
    return boxes


def select_proposals(boxes: np.ndarray, scores: np.ndarray, labels: Sequence[int], prompts: Sequence[str],
                     width: int, height: int, annotations: Sequence[Annotation], target: str,
                     min_score: float) -> list[Proposal]:
    """Candidates of one image: clipped, thresholded, de-duplicated across queries and without what is known.

    Dropped: boxes on an object of the target class that is already annotated, on a hard negative of that class
    (a known non-object) and inside an ignore region (any class).
    """
    boxes = to_image_boxes(boxes, width, height)
    scores = np.asarray(scores, dtype=np.float64)
    keep = (scores >= min_score) & ((boxes[:, 2] - boxes[:, 0]) >= MIN_BOX_PX) & ((boxes[:, 3] - boxes[:, 1]) >= MIN_BOX_PX)
    idx = np.flatnonzero(keep)
    if not idx.size:
        return []
    idx = idx[nms(boxes[idx], scores[idx], NMS_IOU)]

    known = np.array([[a.x1, a.y1, a.x2, a.y2] for a in annotations if a.class_name == target and a.type in ("positive", "hard_negative")]).reshape(-1, 4)
    ignore = np.array([[a.x1, a.y1, a.x2, a.y2] for a in annotations if a.type == "ignore"]).reshape(-1, 4)
    out = []
    for i in idx:
        box = boxes[i : i + 1]
        if len(known) and box_iou(box, known).max() >= KNOWN_IOU:
            continue
        if len(ignore) and box_ioa(box, ignore).max() >= IGNORE_COVERAGE:
            continue
        out.append(Proposal(*(float(v) for v in boxes[i]), float(scores[i]), prompts[int(labels[i])]))
    return out


def example_scores(logits: np.ndarray) -> np.ndarray:
    """OWLv2 logits against example embeddings as 0-1 scores (a raw sigmoid saturates at 1 for everything above ~5)."""
    return 1.0 / (1.0 + np.exp(-(np.asarray(logits, dtype=np.float64) - LOGIT_MIDPOINT) / LOGIT_SCALE))


def pick_example_box(box: Sequence[float], predicted: np.ndarray) -> int | None:
    """Index of the predicted box (xyxy, original pixels) that fits the annotated ``box``, None if none does."""
    if not len(predicted):
        return None
    ious = box_iou(np.array([box], dtype=np.float64), np.asarray(predicted, dtype=np.float64))[0]
    best = int(ious.argmax())
    return best if ious[best] >= EXAMPLE_IOU else None


def rank_example_matches(logits: np.ndarray, objectness: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per box the best example: ``(box indices, scores, example index)`` for the boxes that look like an object at all.

    ``logits`` is ``(boxes, examples)``, ``objectness`` ``(boxes,)``.
    """
    idx = np.flatnonzero(np.asarray(objectness) >= MIN_OBJECTNESS)
    best = np.asarray(logits)[idx].argmax(axis=1)
    return idx, example_scores(np.asarray(logits)[idx, best]), best


# -- job ------------------------------------------------------------------------------------------------------
def _update(search_id: int, **fields) -> None:
    with session_factory()() as session:
        s = session.get(CandidateSearch, search_id)
        for k, v in fields.items():
            setattr(s, k, v)
        session.commit()


def _image_ids(session, search: CandidateSearch) -> list[int]:
    stmt = select(Image.id).where(Image.deleted_at.is_(None), Image.duplicate_of.is_(None))
    if search.scope == "labeled":
        stmt = stmt.where(Image.annotation_status == AnnotationStatus.labeled)
    elif search.scope == "unlabeled":
        stmt = stmt.where(Image.annotation_status == AnnotationStatus.unlabeled)
    stmt = stmt.order_by(Image.id)
    if search.max_images:
        stmt = stmt.limit(search.max_images)
    return list(session.execute(stmt).scalars())


def load_owl(name: str):
    import torch
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        log.warning("no GPU: OWLv2 needs several seconds per image on the CPU")
    processor = Owlv2Processor.from_pretrained(name)
    model = Owlv2ForObjectDetection.from_pretrained(name).to(device).eval()
    return processor, model, device


def detect_batch(processor, model, device: str, images_rgb: list, prompts: list[str]):
    """Raw OWLv2 detections per image: ``(boxes xyxy in original pixels before clipping, scores, prompt index)``."""
    import torch
    from PIL import Image as PilImage

    pil = [PilImage.fromarray(im) for im in images_rgb]
    inputs = processor(text=[prompts] * len(pil), images=pil, return_tensors="pt").to(device)
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device == "cuda"):
        outputs = model(**inputs)
    outputs.logits = outputs.logits.float()
    outputs.pred_boxes = outputs.pred_boxes.float()
    sides = [max(im.shape[0], im.shape[1]) for im in images_rgb]  # boxes are relative to the padded square
    results = processor.post_process_object_detection(outputs, threshold=0.0, target_sizes=torch.tensor([[s, s] for s in sides]))
    return [(r["boxes"].cpu().numpy(), r["scores"].cpu().numpy(), r["labels"].cpu().numpy()) for r in results]


def image_features(processor, model, device: str, images_rgb: list):
    """Per image: image features, boxes (xyxy, original pixels before clipping), objectness and class embeddings."""
    import torch
    from PIL import Image as PilImage

    pixel_values = processor(images=[PilImage.fromarray(im) for im in images_rgb], return_tensors="pt")["pixel_values"].to(device)
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device == "cuda"):
        feature_map = model.image_embedder(pixel_values=pixel_values)[0]
        b, h, w, d = feature_map.shape
        feats = feature_map.reshape(b, h * w, d)
        cxcywh = model.box_predictor(feats, feature_map).float()
        objectness = torch.sigmoid(model.objectness_predictor(feats).float())
        _, class_embeds = model.class_predictor(feats)
    sides = torch.tensor([max(im.shape[0], im.shape[1]) for im in images_rgb], dtype=torch.float32, device=cxcywh.device).view(-1, 1, 1)
    xyxy = torch.cat([cxcywh[..., :2] - cxcywh[..., 2:] / 2, cxcywh[..., :2] + cxcywh[..., 2:] / 2], dim=-1) * sides
    return feats, xyxy.cpu().numpy(), objectness.cpu().numpy(), class_embeds


def example_embeddings(processor, model, device: str, exemplars: list[dict], load) -> tuple:
    """Query embeddings ``(1, n, dim)`` of the example boxes and their names; examples without a fitting box are skipped.

    ``load(image_id)`` returns the RGB image.
    """
    import torch

    embeds, names = [], []
    by_image: dict[int, list[tuple[int, dict]]] = {}
    for k, e in enumerate(exemplars):
        by_image.setdefault(e["image_id"], []).append((k, e))
    for image_id, items in by_image.items():
        _, boxes, _, class_embeds = image_features(processor, model, device, [load(image_id)])
        for k, e in items:
            j = pick_example_box((e["x1"], e["y1"], e["x2"], e["y2"]), boxes[0])
            if j is None:
                log.warning("example %d (image %s): no predicted box fits it, skipped", k + 1, image_id)
                continue
            embeds.append((k, class_embeds[0, j]))
    embeds.sort(key=lambda x: x[0])
    if not embeds:
        raise RuntimeError("none of the example boxes could be used (the model finds no object at their position)")
    return torch.stack([e for _, e in embeds]).unsqueeze(0), [f"Beispiel {k + 1}" for k, _ in embeds]


def detect_batch_examples(processor, model, device: str, images_rgb: list, query_embeds):
    """Like ``detect_batch`` for the example embeddings: only boxes that look like an object are returned."""
    import torch

    feats, boxes, objectness, _ = image_features(processor, model, device, images_rgb)
    with torch.no_grad():
        logits, _ = model.class_predictor(feats, query_embeds.expand(len(images_rgb), -1, -1))
    logits = logits.float().cpu().numpy()
    out = []
    for i in range(len(images_rgb)):
        idx, scores, labels = rank_example_matches(logits[i], objectness[i])
        out.append((boxes[i][idx], scores, labels))
    return out


def run_candidate_search(search_id: int) -> None:
    s3 = storage()
    settings = get_settings()
    with session_factory()() as session:
        search = session.get(CandidateSearch, search_id)
        if search is None or search.status != BatchStatus.queued:
            return  # cancelled while queued
        target, prompts, min_score = search.class_name, list(search.prompts), search.min_score
        mode, exemplars = search.mode, list(search.exemplars or [])
        image_ids = _image_ids(session, search)
    log.info("candidate search #%d: class '%s', %s, %d images", search_id, target,
             prompts if mode == "text" else f"{len(exemplars)} examples", len(image_ids))
    _update(search_id, status=BatchStatus.running, started_at=utcnow(), total=len(image_ids), processed=0, found=0,
            model=settings.candidate_model)
    try:
        processor, model, device = load_owl(settings.candidate_model)
        bucket = s3.settings.bucket_images

        def load_rgb(image_id: int):
            with session_factory()() as session:
                image = session.get(Image, image_id)
                key = image.s3_object_key
            return decode_image(s3.get_bytes(bucket, key))[:, :, ::-1].copy()  # BGR -> RGB

        def load(image_id: int):
            return image_id, load_rgb(image_id)

        query_embeds = None
        if mode == "examples":
            query_embeds, prompts = example_embeddings(processor, model, device, exemplars, load_rgb)  # prompts: names of the examples
            log.info("candidate search #%d: %d of %d examples usable", search_id, len(prompts), len(exemplars))

        found = processed = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for start in range(0, len(image_ids), BATCH_SIZE):
                with session_factory()() as session:
                    if session.get(CandidateSearch, search_id).status == BatchStatus.cancelled:
                        log.info("candidate search #%d cancelled", search_id)
                        return
                batch_ids = image_ids[start : start + BATCH_SIZE]
                loaded = []
                for image_id, result in zip(batch_ids, pool.map(lambda i: _safe(load, i), batch_ids)):
                    if result is not None:
                        loaded.append(result)
                if loaded:
                    images_rgb = [im for _, im in loaded]
                    detections = (detect_batch_examples(processor, model, device, images_rgb, query_embeds) if mode == "examples"
                                  else detect_batch(processor, model, device, images_rgb, prompts))
                    with session_factory()() as session:
                        annotations = {
                            i.id: i.annotations for i in session.execute(
                                select(Image).where(Image.id.in_([i for i, _ in loaded])).options(selectinload(Image.annotations))
                            ).scalars()
                        }
                        for (image_id, im), (boxes, scores, labels) in zip(loaded, detections):
                            h, w = im.shape[:2]
                            for p in select_proposals(boxes, scores, labels, prompts, w, h, annotations.get(image_id, []), target, min_score):
                                session.add(Candidate(search_id=search_id, image_id=image_id, x1=round(p.x1, 1), y1=round(p.y1, 1),
                                                      x2=round(p.x2, 1), y2=round(p.y2, 1), score=round(p.score, 4), prompt=p.prompt[:128]))
                                found += 1
                        session.commit()
                processed += len(batch_ids)
                _update(search_id, processed=processed, found=found)
        _update(search_id, status=BatchStatus.completed, finished_at=utcnow())
        log.info("candidate search #%d finished: %d candidates in %d images", search_id, found, processed)
    except Exception as exc:
        log.exception("candidate search #%d failed", search_id)
        _update(search_id, status=BatchStatus.failed, error=str(exc), finished_at=utcnow())
        raise


def _safe(fn, arg):
    """One unreadable image must not stop the search."""
    try:
        return fn(arg)
    except Exception:
        log.exception("candidate search: image %s skipped", arg)
        return None
