from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from odcore.architectures import BASE_MODELS, get_base_model
from odcore.storage import ObjectStorage

from app.core.database import get_db
from app.core.queue import enqueue_bootstrap
from app.core.s3 import get_storage
from app.db.repositories import models as repo
from app.schemas.model import ModelVersionOut, ModelVersionUpdate
from app.services.model_registry import ModelNotFoundError, ModelRegistry, get_registry, resolve_model

log = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["models"])

ARTIFACTS = {
    "checkpoint": ("checkpoint_key", "application/octet-stream"),
    "onnx": ("onnx_key", "application/octet-stream"),
    "openvino-xml": ("openvino_key", "application/xml"),
    "openvino-bin": (None, "application/octet-stream"),
    "config": ("config_key", "text/x-python"),
}


def to_out(mv) -> ModelVersionOut:
    out = ModelVersionOut.model_validate(mv)
    out.status = mv.status.value
    return out


def get_or_404(session: Session, version: str):
    mv = repo.get_version(session, version)
    if mv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"model version '{version}' not found")
    return mv


@router.get("", response_model=list[ModelVersionOut], summary="List model versions")
def list_models(session: Session = Depends(get_db)) -> list[ModelVersionOut]:
    return [to_out(m) for m in repo.list_versions(session)]


@router.get("/base-models", summary="Selectable COCO-pretrained base models")
def coco_base_models() -> list[dict]:
    return [
        {"id": b.id, "architecture": b.architecture, "label": b.label, "coco_ap": b.coco_ap, "params_m": b.params_m}
        for b in BASE_MODELS
    ]


@router.get("/loaded", summary="Compiled OpenVINO models currently held in memory")
def loaded_models(registry: ModelRegistry = Depends(get_registry)) -> list[dict]:
    return registry.loaded()


@router.post("/bootstrap", status_code=status.HTTP_202_ACCEPTED, summary="Import a COCO-pretrained RTMDet as a model version")
def bootstrap(force: bool = False, base_model: str = "rtmdet-s-coco") -> dict:
    """Queues a job in the trainer that exports the COCO checkpoint of the given
    size (with the configured COCO->class mapping) as a new model version, e.g.
    to test RTMDet-tiny or -M on existing images before training."""
    try:
        get_base_model(base_model)
    except KeyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    try:
        return {"job_id": enqueue_bootstrap(force, base_model)}
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"job queue unavailable: {exc}") from exc


@router.get("/{version}", response_model=ModelVersionOut, summary="Model version details")
def get_model(version: str, session: Session = Depends(get_db)) -> ModelVersionOut:
    if version in ("production", "candidate"):
        try:
            version = resolve_model(session, version).version
        except ModelNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return to_out(get_or_404(session, version))


@router.patch("/{version}", response_model=ModelVersionOut, summary="Update notes of a model version")
def update_model(version: str, body: ModelVersionUpdate, session: Session = Depends(get_db)) -> ModelVersionOut:
    mv = get_or_404(session, version)
    mv.notes = body.notes
    session.commit()
    session.refresh(mv)
    return to_out(mv)


@router.post(
    "/{version}/activate",
    response_model=ModelVersionOut,
    summary="Activate a version as production (promotion or rollback)",
    description="The previous production model is archived. Takes effect for the next /detect request.",
)
def activate_model(version: str, session: Session = Depends(get_db)) -> ModelVersionOut:
    mv = get_or_404(session, version)
    mv = repo.activate(session, mv)
    log.info("model %s is now production", mv.version)
    return to_out(mv)


@router.post("/{version}/archive", response_model=ModelVersionOut, summary="Archive a candidate")
def archive_model(version: str, session: Session = Depends(get_db)) -> ModelVersionOut:
    mv = get_or_404(session, version)
    try:
        mv = repo.archive(session, mv)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return to_out(mv)


@router.get("/{version}/artifacts/{artifact}", summary="Download a model artifact")
def download_artifact(
    version: str,
    artifact: str,
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> StreamingResponse:
    if artifact not in ARTIFACTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown artifact, choose one of {sorted(ARTIFACTS)}")
    mv = get_or_404(session, version)
    attr, media_type = ARTIFACTS[artifact]
    key = getattr(mv, attr) if attr else mv.openvino_key[: -len(".xml")] + ".bin"
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not available")
    body, meta = storage.open_stream(storage.settings.bucket_models, key)
    filename = f"{mv.version}-{os.path.basename(key)}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if meta.get("content_length"):
        headers["Content-Length"] = str(meta["content_length"])
    return StreamingResponse(body.iter_chunks(1024 * 1024), media_type=media_type, headers=headers)
