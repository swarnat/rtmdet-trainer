from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from odcore.db import ModelStatus, ModelVersion, utcnow


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
