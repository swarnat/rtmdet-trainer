from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from odcore.architectures import BASE_MODELS, get_base_model
from odcore.classes import active_class_names, list_classes
from odcore.settings_store import get_setting
from odcore.db import ModelVersion, TrainingRun, TrainingStatus, utcnow
from odcore.geometry import parse_input_size

from app.core.database import get_db
from app.core import queue
from app.core.queue import enqueue_training, get_redis
from app.db.repositories import training as repo
from app.schemas.training import BaseModelOption, TrainingCreate, TrainingEligibility, TrainingLog, TrainingRunOut
from app.services.dataset import eligibility

log = logging.getLogger(__name__)
router = APIRouter(prefix="/training", tags=["training"])



def to_out(run: TrainingRun) -> TrainingRunOut:
    # Built from the columns: the ORM relationship ``model_version`` must not be
    # picked up for the ``model_version`` (version string) field.
    data = {c.name: getattr(run, c.name) for c in TrainingRun.__table__.columns}
    data["status"] = run.status.value
    data["model_version"] = run.model_version.version if run.model_version else None
    return TrainingRunOut.model_validate(data)


def get_run_or_404(session: Session, run_id: int) -> TrainingRun:
    run = session.get(TrainingRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"training run {run_id} not found")
    return run


def resolve_class_names(session, requested: list[str] | None) -> list[str]:
    """Selected classes in configured order; default = all active classes."""
    if not requested:
        names = active_class_names(session)
    else:
        active = [c.name for c in list_classes(session, active_only=True)]
        unknown = [n for n in requested if n not in active]
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown or inactive classes: {unknown}")
        names = [n for n in active if n in set(requested)]
    if not names:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no classes selected")
    return names


@router.get("/eligibility", response_model=TrainingEligibility, summary="Usable images for a class selection")
def get_eligibility(classes: str | None = None, session: Session = Depends(get_db)) -> TrainingEligibility:
    requested = [c for c in (classes or "").split(",") if c]
    return TrainingEligibility(**eligibility(session, resolve_class_names(session, requested)))


@router.get("/base-models", response_model=list[BaseModelOption], summary="Models a training can start from")
def base_models(session: Session = Depends(get_db)) -> list[BaseModelOption]:
    options = [
        BaseModelOption(
            id=b.id,
            label=f"{b.label}",
            description=f"MMDetection checkpoint trained on COCO 2017 (AP {b.coco_ap}, {b.params_m} M parameters); "
            "classification head initialised from the COCO mapping of each class",
            architecture=b.architecture,
            kind="coco",
        )
        for b in BASE_MODELS
    ]
    for mv in session.execute(select(ModelVersion).where(ModelVersion.kind == "trained").order_by(ModelVersion.id.desc())).scalars():
        options.append(
            BaseModelOption(
                id=mv.version,
                label=f"{mv.version} ({mv.architecture}, {mv.status.value})",
                description=f"Continue training from {mv.version} ({mv.input_width}x{mv.input_height}; classes: {', '.join(mv.class_names)})",
                architecture=mv.architecture,
                kind="model",
            )
        )
    return options


@router.get("/gpu", summary="GPU status of the trainer (training requires a GPU)")
def gpu_status() -> dict:
    """``status`` is null while unknown (trainer not running or not yet checked)."""
    return {"status": queue.trainer_gpu_status()}


@router.post("/runs", response_model=TrainingRunOut, status_code=status.HTTP_201_CREATED, summary="Queue a training run")
def create_run(body: TrainingCreate, session: Session = Depends(get_db)) -> TrainingRunOut:
    gpu = queue.trainer_gpu_status()
    if gpu is not None and not gpu.get("available"):
        # unknown status (trainer down) is accepted: the job waits in the queue and the trainer checks again
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"the trainer has no usable GPU ({gpu.get('error') or 'unknown error'}); training requires an NVIDIA GPU. "
            "Re-create the trainer container: docker compose up -d --force-recreate trainer",
        )
    try:
        width, height = parse_input_size(body.input_size)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    base_model_id = body.base_model_id or get_setting(session, "default_base_model")
    try:
        get_base_model(base_model_id)
    except KeyError:
        base = session.execute(select(ModelVersion).where(ModelVersion.version == base_model_id)).scalars().first()
        if base is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown base model '{base_model_id}'")
        if base.kind != "trained":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"'{base.version}' is not a trained model; use one of {[b.id for b in BASE_MODELS]}",
            )

    class_names = resolve_class_names(session, body.class_names)
    elig = eligibility(session, class_names)
    if not elig["usable"]["train"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"no usable labeled images in the train split for classes {class_names} "
            f"({elig['needs_review']} labeled images still need review for these classes)",
        )
    if not elig["usable"]["validation"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no usable labeled images in the validation split (label/review more images or assign one to 'validation')",
        )

    run = TrainingRun(
        status=TrainingStatus.queued,
        base_model_id=base_model_id,
        class_names=class_names,
        input_width=width,
        input_height=height,
        epochs=body.epochs,
        batch_size=body.batch_size,
        learning_rate=body.learning_rate,
        params_json={"num_workers": body.num_workers},
        log="",
    )
    session.add(run)
    session.commit()
    try:
        run.job_id = enqueue_training(run.id)
    except Exception as exc:
        log.exception("could not enqueue training run %s", run.id)
        run.status = TrainingStatus.failed
        run.error = f"could not enqueue job: {exc}"
        run.finished_at = utcnow()
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "job queue unavailable") from exc
    session.commit()
    session.refresh(run)
    log.info("queued training run %s (%s, %dx%d, %d epochs)", run.id, run.base_model_id, width, height, run.epochs)
    return to_out(run)


@router.get("/runs", response_model=list[TrainingRunOut], summary="List training runs")
def list_runs(session: Session = Depends(get_db)) -> list[TrainingRunOut]:
    return [to_out(r) for r in repo.list_runs(session)]


@router.get("/runs/{run_id}", response_model=TrainingRunOut, summary="Training run details")
def get_run(run_id: int, session: Session = Depends(get_db)) -> TrainingRunOut:
    return to_out(get_run_or_404(session, run_id))


@router.get("/runs/{run_id}/log", response_model=TrainingLog, summary="Training log (tail)")
def get_log(run_id: int, session: Session = Depends(get_db)) -> TrainingLog:
    run = get_run_or_404(session, run_id)
    return TrainingLog(id=run.id, status=run.status.value, log=run.log or "")


@router.post("/runs/{run_id}/cancel", response_model=TrainingRunOut, summary="Cancel a queued or running training")
def cancel_run(run_id: int, session: Session = Depends(get_db)) -> TrainingRunOut:
    from rq.command import send_stop_job_command
    from rq.exceptions import InvalidJobOperation, NoSuchJobError
    from rq.job import Job

    run = get_run_or_404(session, run_id)
    if run.status not in (TrainingStatus.queued, TrainingStatus.running):
        raise HTTPException(status.HTTP_409_CONFLICT, f"run is already {run.status.value}")
    if run.job_id:
        redis = get_redis()
        try:
            job = Job.fetch(run.job_id, connection=redis)
            if job.get_status() == "started":
                send_stop_job_command(redis, run.job_id)
            else:
                job.cancel()
        except (NoSuchJobError, InvalidJobOperation):
            pass
    run.status = TrainingStatus.failed
    run.error = "cancelled by user"
    run.finished_at = utcnow()
    session.commit()
    session.refresh(run)
    return to_out(run)
