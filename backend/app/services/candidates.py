"""Candidate searches: turning accepted candidates into annotations.

A candidate is a box proposed by the open-vocabulary detector (``trainer.candidates``) for a class.
Accepting it never overwrites the image: it adds a box, or - if the image already has a box of another
class at that place (the typical split of a class, e.g. "vehicle" -> "excavator") - gives that box the
searched class. The image keeps its labeling status; it is only used for training with the new class
after it was reviewed for it (saved in the annotation tool).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from odcore.classes import list_classes
from odcore.db import Annotation, Candidate, CandidateSearch, Image, utcnow
from odcore.geometry import box_iou

from app.services.duplicates import clear_marks_for

MATCH_IOU = 0.5
SOURCE_MODEL = "owlv2"


def candidate_action(target: str, candidate: Candidate, annotations: list[Annotation]) -> tuple[str, Optional[Annotation]]:
    """``("exists", box)`` if the image already has a box of ``target`` there, ``("reclassify", box)`` for a box
    of another class (real objects only), else ``("new", None)``."""
    boxes = [a for a in annotations if a.type == "positive"]
    if not boxes:
        return "new", None
    ious = box_iou(np.array([[candidate.x1, candidate.y1, candidate.x2, candidate.y2]]),
                   np.array([[a.x1, a.y1, a.x2, a.y2] for a in boxes]))[0]
    order = np.argsort(-ious)
    best = [boxes[i] for i in order if ious[i] >= MATCH_IOU]
    same = next((a for a in best if a.class_name == target), None)
    if same is not None:
        return "exists", same
    if best:
        return "reclassify", best[0]
    return "new", None


def apply_decisions(session: Session, accept_ids: list[int], reject_ids: list[int]) -> dict[str, int]:
    """Accept/reject candidates (any search). Unknown ids are ignored, a search's class must still exist."""
    result = {"added": 0, "reclassified": 0, "already_present": 0, "rejected": 0}
    accept = list(dict.fromkeys(accept_ids))
    reject = [i for i in dict.fromkeys(reject_ids) if i not in set(accept)]
    known = {c.name for c in list_classes(session)}

    if reject:
        for c in session.execute(select(Candidate).where(Candidate.id.in_(reject))).scalars():
            c.status = "rejected"
            result["rejected"] += 1

    rows = session.execute(
        select(Candidate, CandidateSearch.class_name).join(CandidateSearch, CandidateSearch.id == Candidate.search_id)
        .where(Candidate.id.in_(accept)).order_by(Candidate.image_id, Candidate.score.desc())
    ).all() if accept else []
    images: dict[int, Image] = {}
    for candidate, target in rows:
        if target not in known:
            continue
        image = images.get(candidate.image_id)
        if image is None:
            image = images[candidate.image_id] = session.get(Image, candidate.image_id)
        if image is None or image.deleted_at is not None:
            continue
        action, box = candidate_action(target, candidate, list(image.annotations))
        if action == "exists":
            result["already_present"] += 1
        elif action == "reclassify":
            box.class_name = target
            box.updated_at = utcnow()
            result["reclassified"] += 1
        else:
            image.annotations.append(Annotation(
                class_name=target, type="positive", source="prediction", source_model=SOURCE_MODEL,
                x1=round(candidate.x1, 1), y1=round(candidate.y1, 1), x2=round(candidate.x2, 1), y2=round(candidate.y2, 1),
            ))
            clear_marks_for(session, image)  # not an empty image any more
            result["added"] += 1
        candidate.status = "accepted"
        image.updated_at = utcnow()
    session.commit()
    return result
