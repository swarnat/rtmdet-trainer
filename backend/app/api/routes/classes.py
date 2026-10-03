"""Management of the detection classes (incl. COCO mapping)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from odcore.classes import COCO_CLASSES, PALETTE, list_classes, validate_class_name, validate_coco_sources
from odcore.db import Annotation, DetectionClass

from app.core.database import get_db
from app.schemas.classes import ClassOrder, DetectionClassCreate, DetectionClassOut, DetectionClassUpdate

router = APIRouter(prefix="/classes", tags=["classes"])


def _counts(session: Session) -> dict[str, dict[str, int]]:
    """``{class: {"positive": n, "hard_negative": m}}``"""
    result: dict[str, dict[str, int]] = {}
    rows = session.execute(
        select(Annotation.class_name, Annotation.type, func.count(Annotation.id)).group_by(Annotation.class_name, Annotation.type)
    ).all()
    for name, kind, n in rows:
        result.setdefault(name, {})[kind] = n
    return result


def _out(c: DetectionClass, counts: dict[str, dict[str, int]]) -> DetectionClassOut:
    out = DetectionClassOut.model_validate(c)
    out.annotation_count = counts.get(c.name, {}).get("positive", 0)
    out.hard_negative_count = counts.get(c.name, {}).get("hard_negative", 0)
    return out


def _get_or_404(session: Session, name: str) -> DetectionClass:
    c = session.execute(select(DetectionClass).where(DetectionClass.name == name)).scalars().first()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"class '{name}' not found")
    return c


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("", response_model=list[DetectionClassOut], summary="All classes in configured order")
def get_classes(active_only: bool = False, session: Session = Depends(get_db)) -> list[DetectionClassOut]:
    counts = _counts(session)
    return [_out(c, counts) for c in list_classes(session, active_only)]


@router.get("/coco", response_model=list[str], summary="COCO classes available as mapping sources")
def coco_classes() -> list[str]:
    return list(COCO_CLASSES)


@router.post("", response_model=DetectionClassOut, status_code=status.HTTP_201_CREATED, summary="Add a class")
def create_class(body: DetectionClassCreate, session: Session = Depends(get_db)) -> DetectionClassOut:
    try:
        name = validate_class_name(body.name)
        coco = validate_coco_sources(body.coco_classes)
    except ValueError as exc:
        raise _unprocessable(exc) from exc
    existing = list_classes(session)
    if any(c.name == name for c in existing):
        raise HTTPException(status.HTTP_409_CONFLICT, f"class '{name}' already exists")
    c = DetectionClass(
        name=name,
        label=body.label.strip(),
        color=body.color or PALETTE[len(existing) % len(PALETTE)],
        coco_classes=coco,
        sort_order=max((x.sort_order for x in existing), default=-1) + 1,
        active=True,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return _out(c, {})


@router.patch("/{name}", response_model=DetectionClassOut, summary="Change label, colour, COCO mapping or active state")
def update_class(name: str, body: DetectionClassUpdate, session: Session = Depends(get_db)) -> DetectionClassOut:
    c = _get_or_404(session, name)
    if body.label is not None:
        c.label = body.label.strip()
    if body.color is not None:
        c.color = body.color
    if body.coco_classes is not None:
        try:
            c.coco_classes = validate_coco_sources(body.coco_classes)
        except ValueError as exc:
            raise _unprocessable(exc) from exc
    if body.active is not None:
        if not body.active and c.active and len(list_classes(session, active_only=True)) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "at least one class must stay active")
        c.active = body.active
    session.commit()
    session.refresh(c)
    return _out(c, _counts(session))


@router.put("/order", response_model=list[DetectionClassOut], summary="Set the class order (keyboard shortcuts 1-9 follow it)")
def reorder(body: ClassOrder, session: Session = Depends(get_db)) -> list[DetectionClassOut]:
    classes = {c.name: c for c in list_classes(session)}
    if sorted(body.names) != sorted(classes):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "names must contain every class exactly once")
    for i, n in enumerate(body.names):
        classes[n].sort_order = i
    session.commit()
    counts = _counts(session)
    return [_out(c, counts) for c in list_classes(session)]


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an unused class")
def delete_class(name: str, session: Session = Depends(get_db)) -> Response:
    c = _get_or_404(session, name)
    used = sum(_counts(session).get(name, {}).values())
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, f"class '{name}' has {used} annotations; deactivate it instead")
    if c.active and len(list_classes(session, active_only=True)) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "at least one class must stay active")
    session.delete(c)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
