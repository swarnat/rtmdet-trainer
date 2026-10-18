from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from odcore.db import AnnotationStatus, Image, ImageSuggestion
from odcore.storage import ObjectStorage

from app.api.routes.images import store_upload
from app.core.database import get_db
from app.core.s3 import get_storage
from app.schemas.annotation import AnnotationIn
from app.schemas.client_annotator import ClientAnnotatorStatus, ClientImageList, ClientImageSummary, ClientImportResult
from app.services import client_annotator as client
from app.services.annotation import AnnotationValidationError, replace_annotations

log = logging.getLogger(__name__)
router = APIRouter(prefix="/client-annotator", tags=["client annotator"])


def target_or_409(session: Session) -> client.Target:
    try:
        return client.require_target(session)
    except client.NotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("", response_model=ClientAnnotatorStatus, summary="Configuration and image counts of the client annotator")
def get_status(session: Session = Depends(get_db)) -> ClientAnnotatorStatus:
    return ClientAnnotatorStatus(**client.status(session))


@router.post(
    "/config",
    summary="Push the configuration to the client annotator",
    description="Active classes (name, label, color), the inference server as seen from the customer server "
    "(setting client_inference_url, else deployment_url) and default_confidence. Replaces the client's configuration.",
)
def push_config(session: Session = Depends(get_db)) -> dict[str, Any]:
    target_or_409(session)
    try:
        return client.push_config(session)
    except client.ClientAnnotatorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/images", response_model=ClientImageList, summary="Images waiting on the client annotator")
def list_images(session: Session = Depends(get_db)) -> ClientImageList:
    target = target_or_409(session)
    try:
        data = client.list_images(target)
    except client.ClientAnnotatorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return ClientImageList(counts=data["counts"], items=[
        ClientImageSummary(id=i["id"], filename=i["filename"], status=i["status"], annotations=len(i["annotations"]),
                           detections=len(i["detection"]["detections"]) if i["detection"] else None)
        for i in data["items"]
    ])


def apply_client_result(session: Session, image: Image, meta: dict[str, Any]) -> str:
    """Annotated on the client: save as labeled (unless already labeled here). Open with a check: store the
    detections as suggestions (unless the image has suggestions or is labeled already)."""
    if image.annotation_status == AnnotationStatus.labeled:
        return "kept" if meta["status"] == "annotated" else "none"
    if meta["status"] == "annotated":
        locked = session.get(Image, image.id, with_for_update=True, populate_existing=True)
        replace_annotations(session, locked, [AnnotationIn.model_validate(a) for a in meta["annotations"]], mark_labeled=True)
        return "annotations"
    detection = meta.get("detection")
    if not detection or not detection["detections"]:
        return "none"
    if session.execute(select(ImageSuggestion.id).where(ImageSuggestion.image_id == image.id)).first() is not None:
        return "none"
    session.add(ImageSuggestion(
        image_id=image.id, batch_id=None, model_version=str(detection["model_version"])[:32],
        input_width=int(detection["input_width"]), input_height=int(detection["input_height"]),
        confidence=float(detection["confidence"]), detections_json=detection["detections"],
    ))
    session.commit()
    return "suggestions"


@router.post(
    "/images/{client_id}/import",
    response_model=ClientImportResult,
    summary="Import one image of the client annotator and delete it there",
    description="The image is stored like an upload. Annotated on the client: saved here as labeled with its "
    "annotations (an already labeled image keeps its annotations). Open with a check against the inference server: "
    "the detections become suggestions. Afterwards the image is deleted on the client - not after an error, so it "
    "can be imported again. Used by the import dialog: one request per image.",
)
def import_image(client_id: int, session: Session = Depends(get_db), storage: ObjectStorage = Depends(get_storage)) -> ClientImportResult:
    target = target_or_409(session)
    try:
        meta = client.get_image(target, client_id)
        data = client.get_file(target, client_id)
    except client.ClientAnnotatorError as exc:
        return ClientImportResult(client_id=client_id, status="error", error=str(exc))
    filename = meta.get("filename")
    try:
        upload = store_upload(session, storage, filename, data)
    except Exception as exc:
        log.exception("storing client image %s failed", client_id)
        session.rollback()
        return ClientImportResult(client_id=client_id, filename=filename, status="error", error=f"storage error: {exc}")
    if upload.status == "error":
        return ClientImportResult(client_id=client_id, filename=filename, status="error", error=upload.error)
    result = ClientImportResult(client_id=client_id, filename=filename, status=upload.status,
                                image_id=upload.image.id if upload.image else None)
    if upload.status != "deleted":
        try:
            result.applied = apply_client_result(session, session.get(Image, result.image_id), meta)
        except AnnotationValidationError as exc:
            session.rollback()
            return result.model_copy(update={"status": "error", "error": f"annotations not saved: {exc}"})
    try:
        client.delete_image(target, client_id)
        result.client_deleted = True
    except client.ClientAnnotatorError as exc:
        result.error = f"imported, but not deleted on the client: {exc}"
    return result
