from __future__ import annotations

import base64
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from odcore.geometry import decode_image

from app.api.deps import read_upload
from app.core.database import get_db
from app.schemas.detection import DetectResponse, DetectUrlRequest, DetectUrlResponse
from app.services.preprocessing import decode_upload
from app.services.url_download import DownloadError, download_image
from app.services.inference import InvalidRequestError, run_detection
from app.services.model_registry import ModelNotFoundError, ModelRegistry, get_registry

log = logging.getLogger(__name__)
router = APIRouter(tags=["detection"])


def detect_or_http_error(session: Session, registry: ModelRegistry, image, model, input_size, confidence) -> DetectResponse:
    try:
        return run_detection(session, registry, image, model=model, input_size=input_size, confidence=confidence)
    except InvalidRequestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ModelNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND if model not in (None, "", "production") else status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:
        log.exception("detection failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"detection failed: {exc}") from exc


@router.post(
    "/detect",
    response_model=DetectResponse,
    summary="Detect persons, bicycles and vehicles in an image",
    description=(
        "Runs the selected model (default: the active production model) with OpenVINO on CPU. "
        "Boxes are returned in pixel coordinates of the uploaded image. The image is not stored."
    ),
)
async def detect(
    image: Annotated[UploadFile, File(description="JPEG/PNG/WebP/BMP image")],
    model: Annotated[Optional[str], Form(description="'production' (default), 'candidate' or a version like 'model-0003'")] = None,
    input_size: Annotated[Optional[str], Form(description="Model input size WIDTHxHEIGHT, multiples of 32, e.g. 1536x864")] = None,
    confidence: Annotated[Optional[float], Form(description="Confidence threshold, default 0.25")] = None,
    session: Session = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> DetectResponse:
    data = await read_upload(image)
    try:
        decoded = decode_image(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await run_in_threadpool(detect_or_http_error, session, registry, decoded, model, input_size, confidence)


@router.post(
    "/detect/url",
    response_model=DetectUrlResponse,
    summary="Download an image from a URL and run detection on it",
    description=(
        "Like `/detect`, but the API downloads the image itself (works for camera URLs only reachable from the server, "
        "no CORS). The image is not stored; it is returned as data URL for display."
    ),
)
def detect_url(body: DetectUrlRequest, session: Session = Depends(get_db),
               registry: ModelRegistry = Depends(get_registry)) -> DetectUrlResponse:
    try:
        decoded = decode_upload(download_image(body.url.strip()))
    except DownloadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"download failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    result = detect_or_http_error(session, registry, decoded.image, body.model, body.input_size, body.confidence)
    data_url = f"data:{decoded.content_type};base64,{base64.b64encode(decoded.data).decode('ascii')}"
    return DetectUrlResponse(**result.model_dump(), image_data_url=data_url)
