from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from odcore.storage import ObjectStorage

from app.core.database import get_db
from app.core.s3 import get_storage
from app.db.repositories import models as repo
from app.schemas.deployment import DeploymentStatus, DeployRequest
from app.services import deployment

log = logging.getLogger(__name__)
router = APIRouter(prefix="/deployment", tags=["deployment"])


@router.get("", response_model=DeploymentStatus, summary="Model currently active on the production system")
def get_status(session: Session = Depends(get_db)) -> DeploymentStatus:
    return DeploymentStatus(**deployment.status(session))


@router.post(
    "",
    summary="Roll out a model version to the production system",
    description="Uploads the OpenVINO model to the configured production detection API, which replaces its active "
    "model after a successful test run. Independent of the production status in this system.",
)
def deploy(body: DeployRequest, session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)) -> dict[str, Any]:
    mv = repo.get_version(session, body.version)
    if mv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"model version '{body.version}' not found")
    try:
        return deployment.deploy(session, storage, mv)
    except deployment.NotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except deployment.DeploymentError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
