from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from odcore.storage import ObjectStorage

from app.core.config import get_settings
from app.core.database import get_db
from app.core.s3 import get_storage
from app.services import system_reset
from app.services.model_registry import ModelRegistry, get_registry

router = APIRouter(prefix="/system", tags=["system"])


class ResetRequest(BaseModel):
    confirm: str = Field(description=f'must be "{system_reset.CONFIRM_WORD}"')


@router.get("/reset", summary="What a system reset would delete and whether it is possible now")
def reset_preview(session: Session = Depends(get_db)) -> dict[str, Any]:
    return {**system_reset.preview(session), "blocked_by": system_reset.blocking_jobs(session, get_settings().backup_dir)}


@router.post(
    "/reset",
    summary="Reset the system: delete all images, training runs and custom models, restore the default classes",
    description="Irreversible. Keeps the settings, backups and COCO bootstrap models with default classes only "
    "(the newest becomes production if needed; without any, a new COCO import is queued). Refused while a training "
    'run, batch test, benchmark, backup or restore is active. Body: {"confirm": "reset"}.',
)
def reset(
    body: ResetRequest,
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    registry: ModelRegistry = Depends(get_registry),
) -> dict[str, Any]:
    if body.confirm.strip().lower() != system_reset.CONFIRM_WORD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f'confirm with "{system_reset.CONFIRM_WORD}"')
    try:
        return system_reset.reset_system(session, storage, registry, get_settings().backup_dir)
    except system_reset.ResetBlockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
