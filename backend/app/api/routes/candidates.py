"""Candidate search: find objects of a (new) class in the existing images with an open-vocabulary detector.

The detector (OWLv2) runs in the trainer (queued like trainings); this API starts a search, lists the proposed
boxes as crops and turns accepted ones into annotations (see ``app.services.candidates``).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from odcore.classes import active_class_names
from odcore.db import Annotation, BatchStatus, Candidate, CandidateSearch, Image
from odcore.storage import ObjectStorage

from app.core.database import get_db
from app.core.queue import enqueue_candidate_search
from app.core.s3 import get_storage
from app.schemas.candidates import (
    CandidateDecision,
    CandidateDecisionResult,
    CandidateList,
    CandidateOut,
    CandidateSearchIn,
    CandidateSearchOut,
)
from app.services.annotation_crops import CROP_MARGIN, crop_jpeg, decoded_cache
from app.services.candidates import apply_decisions, candidate_action

router = APIRouter(prefix="/candidates", tags=["candidates"])

_active = (BatchStatus.queued, BatchStatus.running)
_live = Image.deleted_at.is_(None)


def get_search_or_404(session: Session, search_id: int) -> CandidateSearch:
    search = session.get(CandidateSearch, search_id)
    if search is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"candidate search {search_id} not found")
    return search


def resolve_exemplars(session: Session, annotation_ids: list[int]) -> list[dict]:
    """Boxes of the chosen annotations (real objects on existing images). The search keeps copies: annotation ids change
    whenever an image is saved."""
    ids = list(dict.fromkeys(annotation_ids))
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "choose at least one example")
    rows = {
        a.id: a for a in session.execute(
            select(Annotation).join(Image, Image.id == Annotation.image_id).where(Annotation.id.in_(ids), Annotation.type == "positive", _live)
        ).scalars()
    }
    missing = [i for i in ids if i not in rows]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"examples not found (or not real objects): {missing}")
    return [{"image_id": rows[i].image_id, "class": rows[i].class_name, "x1": rows[i].x1, "y1": rows[i].y1, "x2": rows[i].x2, "y2": rows[i].y2}
            for i in ids]


def search_out(session: Session, searches: list[CandidateSearch]) -> list[CandidateSearchOut]:
    counts: dict[int, dict[str, int]] = {}
    if searches:
        rows = session.execute(
            select(Candidate.search_id, Candidate.status, func.count())
            .join(Image, Image.id == Candidate.image_id).where(_live, Candidate.search_id.in_([s.id for s in searches]))
            .group_by(Candidate.search_id, Candidate.status)
        ).all()
        for sid, st, n in rows:
            counts.setdefault(sid, {})[st] = n
    out = []
    for s in searches:
        o = CandidateSearchOut.model_validate(s)
        o.status = s.status.value
        o.examples = len(s.exemplars or [])
        c = counts.get(s.id, {})
        o.pending, o.accepted, o.rejected = c.get("pending", 0), c.get("accepted", 0), c.get("rejected", 0)
        out.append(o)
    return out


@router.post(
    "/searches",
    response_model=CandidateSearchOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a search for objects of a class (text query or example boxes) in the existing images",
    description="Runs in the trainer (GPU recommended). One search at a time. Results appear while it runs. "
    "mode=text needs `prompts`; mode=examples needs `exemplar_ids` (annotations that show what to look for).",
)
def start_search(body: CandidateSearchIn, session: Session = Depends(get_db)) -> CandidateSearchOut:
    if body.class_name not in active_class_names(session):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown or inactive class '{body.class_name}'")
    prompts, exemplars = [], []
    if body.mode == "text":
        prompts = list(dict.fromkeys(p.strip() for p in body.prompts if p.strip()))
        if not prompts or any(len(p) > 128 for p in prompts):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "prompts must be 1-128 characters")
    else:
        exemplars = resolve_exemplars(session, body.exemplar_ids)
    running = session.execute(select(CandidateSearch.id).where(CandidateSearch.status.in_(_active))).first()
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"search #{running[0]} is still running")
    search = CandidateSearch(class_name=body.class_name, mode=body.mode, prompts=prompts, exemplars=exemplars, scope=body.scope,
                             max_images=body.max_images, min_score=body.min_score, status=BatchStatus.queued)
    session.add(search)
    session.commit()
    try:
        enqueue_candidate_search(search.id)
    except Exception as exc:
        search.status, search.error = BatchStatus.failed, f"could not queue the job: {exc}"
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, search.error) from exc
    session.refresh(search)
    return search_out(session, [search])[0]


@router.get("/searches", response_model=list[CandidateSearchOut], summary="Searches, newest first")
def list_searches(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_db)) -> list[CandidateSearchOut]:
    searches = list(session.execute(select(CandidateSearch).order_by(CandidateSearch.id.desc()).limit(limit)).scalars())
    return search_out(session, searches)


@router.get("/searches/{search_id}", response_model=CandidateSearchOut, summary="Progress and counts of one search")
def get_search(search_id: int, session: Session = Depends(get_db)) -> CandidateSearchOut:
    return search_out(session, [get_search_or_404(session, search_id)])[0]


@router.post("/searches/{search_id}/cancel", response_model=CandidateSearchOut, summary="Stop a queued or running search")
def cancel_search(search_id: int, session: Session = Depends(get_db)) -> CandidateSearchOut:
    search = get_search_or_404(session, search_id)
    if search.status in _active:
        # the job checks the status between batches; found candidates are kept
        search.status = BatchStatus.cancelled
        session.commit()
        session.refresh(search)
    return search_out(session, [search])[0]


@router.delete("/searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a search with its candidates")
def delete_search(search_id: int, session: Session = Depends(get_db)) -> Response:
    search = get_search_or_404(session, search_id)
    if search.status in _active:
        raise HTTPException(status.HTTP_409_CONFLICT, "stop the search first")
    session.execute(delete(Candidate).where(Candidate.search_id == search_id))
    session.delete(search)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/searches/{search_id}/items", response_model=CandidateList, summary="Candidates of a search (for crops)")
def list_candidates(
    search_id: int,
    state: Literal["pending", "accepted", "rejected"] = Query("pending", alias="status"),
    min_score: float = Query(0.0, ge=0, le=1),
    sort: Literal["score", "image"] = "score",
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    session: Session = Depends(get_db),
) -> CandidateList:
    search = get_search_or_404(session, search_id)
    where = [Candidate.search_id == search_id, Candidate.status == state, Candidate.score >= min_score, _live]
    base = select(Candidate, Image.width, Image.height).join(Image, Image.id == Candidate.image_id).where(*where)
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    order = (Candidate.score.desc(), Candidate.id) if sort == "score" else (Candidate.image_id, Candidate.score.desc())
    rows = session.execute(base.order_by(*order).offset(offset).limit(limit)).all()
    annotations: dict[int, list[Annotation]] = {}
    image_ids = {c.image_id for c, _, _ in rows}
    if image_ids:
        for a in session.execute(select(Annotation).where(Annotation.image_id.in_(image_ids))).scalars():
            annotations.setdefault(a.image_id, []).append(a)
    items = []
    for c, w, h in rows:
        action, box = candidate_action(search.class_name, c, annotations.get(c.image_id, []))
        items.append(CandidateOut(
            id=c.id, image_id=c.image_id, x1=c.x1, y1=c.y1, x2=c.x2, y2=c.y2, score=c.score, prompt=c.prompt, status=c.status,
            image_width=w, image_height=h, action=action, current_class=box.class_name if box else None,
        ))
    return CandidateList(total=total, margin=CROP_MARGIN, items=items)


@router.post("/decide", response_model=CandidateDecisionResult, summary="Accept / reject candidates")
def decide(body: CandidateDecision, session: Session = Depends(get_db)) -> CandidateDecisionResult:
    return CandidateDecisionResult(**apply_decisions(session, body.accept, body.reject))


@router.get("/{candidate_id}/crop", summary="JPEG crop of the candidate box plus 20 px context", response_class=Response)
def candidate_crop(candidate_id: int, session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)) -> Response:
    row = session.execute(
        select(Candidate, Image.s3_object_key).join(Image, Image.id == Candidate.image_id).where(Candidate.id == candidate_id, _live)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"candidate {candidate_id} not found")
    c, key = row
    image = decoded_cache.get(c.image_id, lambda: storage.get_bytes(storage.settings.bucket_images, key))
    # a candidate box never changes: the crop can be cached for good
    return Response(crop_jpeg(image, (c.x1, c.y1, c.x2, c.y2)), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400, immutable"})
