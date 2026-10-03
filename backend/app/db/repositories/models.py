from __future__ import annotations

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from odcore.db import BatchStatus, ModelStatus, ModelVersion, PredictionBatch, TrainingRun, TrainingStatus, utcnow


def list_versions(session: Session) -> list[ModelVersion]:
    return list(session.execute(select(ModelVersion).order_by(ModelVersion.id.desc())).scalars().all())


def get_version(session: Session, version: str) -> ModelVersion | None:
    return session.execute(select(ModelVersion).where(ModelVersion.version == version)).scalars().first()


def activate(session: Session, mv: ModelVersion) -> ModelVersion:
    """Make ``mv`` production; the previous production model becomes archived.

    Works for candidates (promotion) and archived versions (rollback). The
    partial unique index guarantees there is never more than one production row.
    """
    if mv.status == ModelStatus.production:
        return mv
    # Lock the rows involved to serialise concurrent activations.
    session.execute(select(ModelVersion.id).where(ModelVersion.status == ModelStatus.production).with_for_update())
    session.execute(
        update(ModelVersion)
        .where(ModelVersion.status == ModelStatus.production)
        .values(status=ModelStatus.archived)
    )
    session.flush()
    mv.status = ModelStatus.production
    mv.activated_at = utcnow()
    session.commit()
    session.refresh(mv)
    return mv


def archive(session: Session, mv: ModelVersion) -> ModelVersion:
    if mv.status == ModelStatus.production:
        raise ValueError("the production model cannot be archived; activate another version first")
    mv.status = ModelStatus.archived
    session.commit()
    session.refresh(mv)
    return mv


def delete(session: Session, mv: ModelVersion) -> None:
    """Remove the database row of a model version (artifacts are removed by the caller).

    Refused for the production model and while a training run or batch test still uses it.
    Finished training runs stay in the history without their link to the model.
    """
    if mv.status == ModelStatus.production:
        raise ValueError("the production model cannot be deleted; activate another version first")
    active_runs = session.scalar(
        select(func.count(TrainingRun.id)).where(
            TrainingRun.base_model_id == mv.version,
            TrainingRun.status.in_([TrainingStatus.queued, TrainingStatus.running]),
        )
    )
    if active_runs:
        raise ValueError(f"{mv.version} is the base model of a queued or running training run")
    active_batches = session.scalar(
        select(func.count(PredictionBatch.id)).where(
            or_(PredictionBatch.model_version == mv.version, PredictionBatch.model_ref == mv.version),
            PredictionBatch.status.in_([BatchStatus.queued, BatchStatus.running]),
        )
    )
    if active_batches:
        raise ValueError(f"{mv.version} is used by a queued or running batch test")
    session.execute(update(TrainingRun).where(TrainingRun.model_version_id == mv.id).values(model_version_id=None))
    session.delete(mv)
    session.commit()
