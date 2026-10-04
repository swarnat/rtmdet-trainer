"""Detection API for the production system.

* ``POST /api/v1/detect``  image in, detected objects and category list out (JSON)
* ``PUT  /api/v1/model``   install a new model (access key required); replaces the active model
* ``GET  /api/v1/model``   the active model
* ``GET  /api/v1/health``  liveness (also without a model)
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from odcore.geometry import decode_image

from app.config import MIN_ACCESS_KEY_LENGTH, Settings, get_settings
from app.cpu import CpuCheck, check_cpu
from app.model_store import ActiveModel, InvalidModelError, ModelManifest, ModelStore, NoModelError

log = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


# -- schemas -----------------------------------------------------------------------
class BBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class DetectionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_name: str = Field(serialization_alias="class")
    confidence: float
    bbox: BBox = Field(description="pixel coordinates in the uploaded image")


class CategoryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_name: str = Field(serialization_alias="class")
    count: int
    max_confidence: float


class ModelInfo(BaseModel):
    version: str
    architecture: Optional[str]
    class_names: list[str]
    input_width: int
    input_height: int
    installed_at: Optional[str]


class ImageInfo(BaseModel):
    width: int
    height: int


class DetectResponse(BaseModel):
    model: ModelInfo
    image: ImageInfo
    confidence_threshold: float
    inference_ms: float
    categories: list[CategoryOut] = Field(description="detected classes, highest confidence first")
    detections: list[DetectionOut]


class CpuInfo(BaseModel):
    model: Optional[str]
    supported: Optional[bool] = Field(description="False: models cannot be loaded; None: not checked (non-Linux)")
    missing_required: list[str]
    missing_recommended: list[str]


class Health(BaseModel):
    status: str
    model_loaded: bool
    model_version: Optional[str]
    uploads_enabled: bool
    cpu: CpuInfo
    warnings: list[str] = Field(description="problems an operator should fix (e.g. missing CPU instruction sets)")


def model_info(model: ActiveModel) -> ModelInfo:
    m = model.manifest
    return ModelInfo(version=m.version, architecture=m.architecture, class_names=m.class_names, input_width=m.input_width,
                     input_height=m.input_height, installed_at=m.installed_at.isoformat() if m.installed_at else None)


# -- app -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.uploads_enabled:
        log.warning("model uploads are disabled: set MODEL_UPLOAD_KEY (at least %d characters)", MIN_ACCESS_KEY_LENGTH)
    cpu = check_cpu()
    app.state.cpu = cpu
    for warning in cpu.warnings():
        (log.error if cpu.missing_required else log.warning)("%s (CPU model: %s)", warning, cpu.model)
    store = ModelStore(settings.model_dir, settings.openvino_device)
    store.load_active()
    app.state.store = store
    yield


app = FastAPI(
    title="Object Detection – Inference API",
    version="0.1.0",
    description="Detects objects in an image with the active model. The model is installed by the training system via PUT /api/v1/model.",
    lifespan=lifespan,
    docs_url=f"{API_PREFIX}/docs",
    openapi_url=f"{API_PREFIX}/openapi.json",
)


def get_store(request: Request) -> ModelStore:
    return request.app.state.store


def get_cpu(request: Request) -> CpuCheck:
    return request.app.state.cpu


async def read_limited(file: UploadFile, max_mb: int) -> bytes:
    limit = max_mb * 1024 * 1024
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file exceeds {max_mb} MB")
        chunks.append(chunk)
    return b"".join(chunks)


def require_upload_key(
    x_access_key: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.uploads_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"model uploads are disabled (MODEL_UPLOAD_KEY not set or shorter than {MIN_ACCESS_KEY_LENGTH} characters)",
        )
    supplied = x_access_key
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), settings.model_upload_key.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing access key", headers={"WWW-Authenticate": "Bearer"})


@app.get(f"{API_PREFIX}/health", response_model=Health, tags=["status"])
def health(store: ModelStore = Depends(get_store), settings: Settings = Depends(get_settings),
           cpu: CpuCheck = Depends(get_cpu)) -> Health:
    model = store.active()
    warnings = cpu.warnings()
    if not settings.uploads_enabled:
        warnings.append(f"model uploads are disabled: set MODEL_UPLOAD_KEY (at least {MIN_ACCESS_KEY_LENGTH} characters)")
    return Health(
        status="ok" if cpu.supported is not False else "degraded",
        model_loaded=model is not None,
        model_version=model.manifest.version if model else None,
        uploads_enabled=settings.uploads_enabled,
        cpu=CpuInfo(model=cpu.model, supported=cpu.supported, missing_required=cpu.missing_required,
                    missing_recommended=cpu.missing_recommended),
        warnings=warnings,
    )


@app.get(f"{API_PREFIX}/model", response_model=ModelInfo, tags=["model"], summary="The active model")
def get_model(store: ModelStore = Depends(get_store)) -> ModelInfo:
    model = store.active()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no model installed yet")
    return model_info(model)


@app.put(
    f"{API_PREFIX}/model",
    response_model=ModelInfo,
    tags=["model"],
    summary="Install a model and make it the active one",
    description="Multipart upload: `manifest` (JSON), `model_xml` and `model_bin` (OpenVINO IR). Requires the access key "
    "(header `X-Access-Key` or `Authorization: Bearer`). The model is compiled and test-run before it replaces the "
    "active model; if that fails, the previous model stays active.",
    dependencies=[Depends(require_upload_key)],
)
async def put_model(
    manifest: Annotated[str, Form(description="JSON: version, class_names, input_width, input_height, nms_iou_threshold, …")],
    model_xml: Annotated[UploadFile, File(description="OpenVINO model.xml")],
    model_bin: Annotated[UploadFile, File(description="OpenVINO model.bin")],
    store: ModelStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
    cpu: CpuCheck = Depends(get_cpu),
) -> ModelInfo:
    try:
        parsed = ModelManifest.model_validate_json(manifest)
    except ValidationError as exc:
        log.warning("model upload rejected: invalid manifest: %s", exc)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid manifest: {exc}") from exc
    try:
        model = await run_in_threadpool(
            store.install, parsed, model_xml.file, model_bin.file, settings.max_model_upload_mb * 1024 * 1024
        )
    except InvalidModelError as exc:
        detail = str(exc)
        if cpu.missing_required:  # the usual reason why a valid model cannot be loaded
            detail = f"{detail} | {cpu.warnings()[0]}"
        log.warning("model upload %s rejected: %s", parsed.version, detail)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail) from exc
    return model_info(model)


@app.post(
    f"{API_PREFIX}/detect",
    response_model=DetectResponse,
    tags=["detection"],
    summary="Detect objects in an image",
    description="Returns the detected objects (boxes in pixels of the uploaded image) and the list of detected categories. "
    "The image is not stored.",
)
async def detect(
    image: Annotated[UploadFile, File(description="JPEG/PNG/WebP/BMP image")],
    confidence: Annotated[Optional[float], Form(description="minimum confidence, default and lowest allowed value: MIN_CONFIDENCE (0.15)")] = None,
    store: ModelStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> DetectResponse:
    threshold = settings.min_confidence if confidence is None else confidence
    if not settings.min_confidence <= threshold <= 1.0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"confidence must be in [{settings.min_confidence}, 1]")
    data = await read_limited(image, settings.max_upload_mb)
    try:
        decoded = decode_image(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    try:
        model, result = await run_in_threadpool(store.detect, decoded, threshold)
    except NoModelError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    names = model.manifest.class_names
    detections = [
        DetectionOut(class_name=names[d.class_id], confidence=round(d.confidence, 4),
                     bbox=BBox(x1=round(d.x1), y1=round(d.y1), x2=round(d.x2), y2=round(d.y2)))
        for d in result.detections
    ]
    categories: dict[str, CategoryOut] = {}
    for d in detections:  # detections are sorted by confidence, so the first one per class is its maximum
        c = categories.setdefault(d.class_name, CategoryOut(class_name=d.class_name, count=0, max_confidence=d.confidence))
        c.count += 1
    return DetectResponse(
        model=model_info(model),
        image=ImageInfo(width=int(decoded.shape[1]), height=int(decoded.shape[0])),
        confidence_threshold=threshold,
        inference_ms=round(result.inference_ms, 1),
        categories=list(categories.values()),
        detections=detections,
    )
