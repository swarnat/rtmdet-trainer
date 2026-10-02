from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from odcore.db import TrainingRun, TrainingStatus


def list_runs(session: Session, limit: int = 50) -> list[TrainingRun]:
    return list(session.execute(select(TrainingRun).order_by(TrainingRun.id.desc()).limit(limit)).scalars().all())


def active_runs(session: Session) -> list[TrainingRun]:
    return list(
        session.execute(
            select(TrainingRun).where(TrainingRun.status.in_([TrainingStatus.queued, TrainingStatus.running]))
        ).scalars().all()
    )
