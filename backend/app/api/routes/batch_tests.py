"""Batch test: suggestions for all open images from one model run."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from odcore.db import BatchStatus, PredictionBatch, utcnow
from odcore.settings_store import get_setting

from app.core.database import get_db
from app.schemas.batch_test import BatchTestCreate, BatchTestOut
from app.services.batch_test import ERROR_SCOPES, get_runner, select_image_ids
from app.services.inference import InvalidRequestError, resolve_parameters
from app.services.model_registry import ModelNotFoundError, resolve_model

router = APIRouter(prefix="/batch-tests", tags=["batch tests"])


def to_out(b: PredictionBatch) -> BatchTestOut:
    out = BatchTestOut.model_validate(b)
    out.status = b.status.value
    return out


def get_or_404(session: Session, batch_id: int) -> PredictionBatch:
    b = session.get(PredictionBatch, batch_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"batch test {batch_id} not found")
    return b


@router.post(
    "",
    response_model=BatchTestOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a model over all open images and store suggestions, or analyse its errors on labeled images",
    description="Runs in the background inside the API (one batch at a time). Existing suggestions of the "
    "affected images are replaced; annotations are not changed. Scopes errors_validation / errors_labeled run an "
    "error analysis instead: images where the model produces false positives or false negatives are marked "
    "(replacing all marks of the previous analysis). Its default confidence is the setting eval_confidence, "
    "as in the training evaluation.",
)
def start(body: BatchTestCreate, session: Session = Depends(get_db)) -> BatchTestOut:
    confidence = body.confidence
    if confidence is None and body.scope in ERROR_SCOPES:
        confidence = float(get_setting(session, "eval_confidence"))
    try:
        width, height, conf = resolve_parameters(session, body.input_size, confidence)
        ref = resolve_model(session, body.model)
    except InvalidRequestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ModelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    active = session.execute(
        select(PredictionBatch.id).where(PredictionBatch.status.in_([BatchStatus.queued, BatchStatus.running]))
    ).first()
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"batch test #{active[0]} is still running")
    if not select_image_ids(session, body.scope):
        raise HTTPException(status.HTTP_409_CONFLICT, "no images in scope")
    batch = PredictionBatch(
        status=BatchStatus.queued, model_ref=body.model, model_version=ref.version, input_width=width,
        input_height=height, confidence=conf, scope=body.scope,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    get_runner().submit(batch.id)
    return to_out(batch)


@router.get("", response_model=list[BatchTestOut], summary="Recent batch tests")
def list_batches(limit: int = 20, session: Session = Depends(get_db)) -> list[BatchTestOut]:
    rows = session.execute(select(PredictionBatch).order_by(PredictionBatch.id.desc()).limit(limit)).scalars()
    return [to_out(b) for b in rows]


@router.get("/{batch_id}", response_model=BatchTestOut, summary="Batch test status and progress")
def get_batch(batch_id: int, session: Session = Depends(get_db)) -> BatchTestOut:
    return to_out(get_or_404(session, batch_id))


@router.post("/{batch_id}/cancel", response_model=BatchTestOut, summary="Stop a running batch test")
def cancel(batch_id: int, session: Session = Depends(get_db)) -> BatchTestOut:
    b = get_or_404(session, batch_id)
    if b.status not in (BatchStatus.queued, BatchStatus.running):
        raise HTTPException(status.HTTP_409_CONFLICT, f"batch test is already {b.status.value}")
    b.status, b.finished_at = BatchStatus.cancelled, utcnow()
    session.commit()
    session.refresh(b)
    return to_out(b)
