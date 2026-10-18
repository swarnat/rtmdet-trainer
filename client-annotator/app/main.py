"""Client annotator: annotation service that runs directly on a customer server.

* batch download of images from URLs (like the annotation view of the training system) and uploads
* check of an image against the inference server, annotation in the web UI
* the training system pushes the configuration (``PUT /api/v1/config``), fetches the images with their
  annotations (``GET /api/v1/images`` + ``/file``) and deletes each one after the import

Every call except ``/health`` needs the access token (CLIENT_ACCESS_TOKEN): header ``X-Access-Key``,
``Authorization: Bearer <token>`` or the cookie set by ``POST /api/v1/session`` (web UI).
"""
from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, Optional

import httpx
from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from odcore.download import DownloadError, download_image, filename_from_url
from odcore.geometry import normalize_box
from odcore.images import decode_upload

from app.config import MIN_ACCESS_TOKEN_LENGTH, Settings, get_settings
from app.store import Store, utcnow

log = logging.getLogger(__name__)
API_PREFIX = "/api/v1"
COOKIE_NAME = "client_annotator_token"
DETECT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


# -- schemas -----------------------------------------------------------------------
class ClassConfig(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=64)
    color: str = Field("#9e9e9e", max_length=16)


class ConfigIn(BaseModel):
    classes: list[ClassConfig] = Field(min_length=1, description="classes that can be annotated, in display order")
    inference_url: str = Field("", max_length=512, description="inference server as seen from this server (\"\" = no checks)")
    confidence: float = Field(0.25, gt=0, le=1, description="threshold for checks against the inference server")
    source: Optional[str] = Field(None, max_length=256, description="who pushed the configuration (informational)")

    @field_validator("inference_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("inference_url must start with http:// or https://")
        return v


class ConfigOut(ConfigIn):
    pushed_at: str
    # "env": confidence comes from CHECK_CONFIDENCE and overrides the pushed value (pushed_confidence)
    confidence_source: Literal["pushed", "env"] = "pushed"
    pushed_confidence: Optional[float] = None


class AnnotationIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_name: str = Field(validation_alias="class", serialization_alias="class", max_length=32)
    x1: float
    y1: float
    x2: float
    y2: float
    type: Literal["positive", "hard_negative"] = "positive"
    source: Literal["manual", "prediction"] = "manual"
    source_confidence: Optional[float] = Field(None, ge=0, le=1)
    source_model: Optional[str] = Field(None, max_length=32)


class AnnotationsSave(BaseModel):
    annotations: list[AnnotationIn]
    # true: the image is done (an empty list = negative image); false: only keep the boxes
    mark_annotated: bool = True


class StatusUpdate(BaseModel):
    status: Literal["open"]


class ImageOut(BaseModel):
    id: int
    sha256: str
    filename: Optional[str]
    source_url: Optional[str]
    content_type: str
    size_bytes: int
    width: int
    height: int
    status: Literal["open", "annotated"]
    annotations: list[dict[str, Any]]
    detection: Optional[dict[str, Any]]
    created_at: str
    updated_at: str
    annotated_at: Optional[str]


class Counts(BaseModel):
    total: int
    open: int
    annotated: int


class ImageList(BaseModel):
    counts: Counts
    items: list[ImageOut]


class UploadResult(BaseModel):
    filename: Optional[str]
    status: Literal["created", "duplicate", "error"]
    image: Optional[ImageOut] = None
    error: Optional[str] = None


class UrlDownload(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class DetectRequest(BaseModel):
    confidence: Optional[float] = Field(None, gt=0, le=1, description="default: confidence of the configuration")


class SessionIn(BaseModel):
    token: str


class Health(BaseModel):
    status: str
    token_configured: bool
    configured: bool = Field(description="a configuration was pushed by the training system")


# -- app ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.token_valid:
        log.error("API disabled: set CLIENT_ACCESS_TOKEN (at least %d characters)", MIN_ACCESS_TOKEN_LENGTH)
    app.state.store = Store(settings.data_dir)
    yield


app = FastAPI(
    title="Object Detection – Client Annotator",
    version="0.1.0",
    description="Annotation service on the customer server. Fetched and emptied by the training system.",
    lifespan=lifespan,
    docs_url=f"{API_PREFIX}/docs",
    openapi_url=f"{API_PREFIX}/openapi.json",
)


def get_store(request: Request) -> Store:
    return request.app.state.store


def inference_client() -> httpx.Client:
    """Separate function so tests can substitute the transport."""
    return httpx.Client(timeout=DETECT_TIMEOUT)


def _token_ok(supplied: Optional[str], settings: Settings) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied.encode(), settings.access_token.encode())


def require_token(
    x_access_key: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    cookie: Annotated[Optional[str], Cookie(alias=COOKIE_NAME)] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.token_valid:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"API disabled (CLIENT_ACCESS_TOKEN not set or shorter than {MIN_ACCESS_TOKEN_LENGTH} characters)",
        )
    supplied = x_access_key
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not _token_ok(supplied or cookie, settings):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing access token", headers={"WWW-Authenticate": "Bearer"})


def get_image_or_404(store: Store, image_id: int) -> dict[str, Any]:
    image = store.get(image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"image {image_id} not found")
    return image


def effective_config(config: Optional[dict[str, Any]], settings: Settings) -> Optional[dict[str, Any]]:
    """The pushed configuration with CHECK_CONFIDENCE applied (if set)."""
    if config is None:
        return None
    pushed = config["confidence"]
    if settings.check_confidence is None:
        return {**config, "confidence_source": "pushed", "pushed_confidence": pushed}
    return {**config, "confidence": settings.check_confidence, "confidence_source": "env", "pushed_confidence": pushed}


def get_config_or_409(store: Store, settings: Settings) -> dict[str, Any]:
    config = effective_config(store.get_config(), settings)
    if config is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "not configured yet: push the configuration from the training system")
    return config


def store_upload(store: Store, filename: Optional[str], data: bytes, source_url: Optional[str] = None) -> UploadResult:
    try:
        decoded = decode_upload(data)
    except ValueError as exc:
        return UploadResult(filename=filename, status="error", error=str(exc))
    image, created = store.add(decoded, filename, source_url)
    return UploadResult(filename=filename, status="created" if created else "duplicate", image=ImageOut(**image))


auth = [Depends(require_token)]


@app.get(f"{API_PREFIX}/health", response_model=Health, tags=["status"])
def health(store: Store = Depends(get_store), settings: Settings = Depends(get_settings)) -> Health:
    return Health(status="ok" if settings.token_valid else "disabled", token_configured=settings.token_valid,
                  configured=store.get_config() is not None)


@app.post(f"{API_PREFIX}/session", status_code=status.HTTP_204_NO_CONTENT, tags=["session"], summary="Web UI login (sets a cookie)")
def login(body: SessionIn, request: Request, settings: Settings = Depends(get_settings)) -> Response:
    if not settings.token_valid:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API disabled (CLIENT_ACCESS_TOKEN not set)")
    if not _token_ok(body.token.strip(), settings):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid access token")
    res = Response(status_code=status.HTTP_204_NO_CONTENT)
    res.set_cookie(COOKIE_NAME, body.token.strip(), max_age=30 * 24 * 3600, httponly=True, samesite="strict",
                   secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return res


@app.delete(f"{API_PREFIX}/session", status_code=status.HTTP_204_NO_CONTENT, tags=["session"], summary="Web UI logout")
def logout() -> Response:
    res = Response(status_code=status.HTTP_204_NO_CONTENT)
    res.delete_cookie(COOKIE_NAME)
    return res


@app.get(f"{API_PREFIX}/config", response_model=Optional[ConfigOut], tags=["config"], dependencies=auth,
         summary="Configuration pushed by the training system (null = none yet)")
def get_config(store: Store = Depends(get_store), settings: Settings = Depends(get_settings)) -> Optional[ConfigOut]:
    config = effective_config(store.get_config(), settings)
    return ConfigOut(**config) if config else None


@app.put(f"{API_PREFIX}/config", response_model=ConfigOut, tags=["config"], dependencies=auth,
         summary="Replace the configuration (classes, inference server, confidence)")
def put_config(body: ConfigIn, store: Store = Depends(get_store), settings: Settings = Depends(get_settings)) -> ConfigOut:
    names = [c.name for c in body.classes]
    if len(set(names)) != len(names):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "class names must be unique")
    config = {**body.model_dump(), "pushed_at": utcnow()}
    store.set_config(config)
    log.info("configuration pushed (%d classes, inference server %s)", len(names), body.inference_url or "-")
    return ConfigOut(**effective_config(config, settings))


@app.get(f"{API_PREFIX}/images", response_model=ImageList, tags=["images"], dependencies=auth,
         summary="All images with annotations and the latest check")
def list_images(status_filter: Annotated[Optional[Literal["open", "annotated"]], Query(alias="status")] = None,
                limit: Annotated[Optional[int], Query(ge=0, description="at most this many items (0 = counts only)")] = None,
                store: Store = Depends(get_store)) -> ImageList:
    return ImageList(counts=Counts(**store.counts()), items=[ImageOut(**i) for i in store.list(status_filter, limit)])


@app.post(f"{API_PREFIX}/images", response_model=list[UploadResult], tags=["images"], dependencies=auth,
          summary="Upload one or more images")
async def upload_images(
    files: Annotated[list[UploadFile], File(description="JPEG/PNG/WebP/BMP")],
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> list[UploadResult]:
    limit = settings.max_upload_mb * 1024 * 1024
    results = []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            results.append(UploadResult(filename=f.filename, status="error", error=f"file exceeds {settings.max_upload_mb} MB"))
            continue
        results.append(await run_in_threadpool(store_upload, store, f.filename, data))
    return results


@app.post(f"{API_PREFIX}/images/from-url", response_model=UploadResult, tags=["images"], dependencies=auth,
          summary="Download an image from a URL (batch download: one request per URL)")
def download_from_url(body: UrlDownload, store: Store = Depends(get_store), settings: Settings = Depends(get_settings)) -> UploadResult:
    url = body.url.strip()
    filename = filename_from_url(url)
    try:
        data = download_image(url, settings.max_upload_mb, settings.download_proxy)
    except DownloadError as exc:
        return UploadResult(filename=filename, status="error", error=str(exc))
    return store_upload(store, filename, data, url)


@app.get(f"{API_PREFIX}/images/{{image_id}}", response_model=ImageOut, tags=["images"], dependencies=auth)
def get_image(image_id: int, store: Store = Depends(get_store)) -> ImageOut:
    return ImageOut(**get_image_or_404(store, image_id))


@app.get(f"{API_PREFIX}/images/{{image_id}}/file", response_class=FileResponse, tags=["images"], dependencies=auth,
         summary="Original image file")
def image_file(image_id: int, store: Store = Depends(get_store)) -> FileResponse:
    image = get_image_or_404(store, image_id)
    return FileResponse(store.file_path(image), media_type=image["content_type"], filename=image["filename"] or None,
                        headers={"Cache-Control": "private, max-age=86400, immutable"})


@app.get(f"{API_PREFIX}/images/{{image_id}}/thumbnail", response_class=FileResponse, tags=["images"], dependencies=auth)
def image_thumbnail(image_id: int, store: Store = Depends(get_store)) -> FileResponse:
    image = get_image_or_404(store, image_id)
    return FileResponse(store.thumbnail_path(image), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400, immutable"})


@app.put(f"{API_PREFIX}/images/{{image_id}}/annotations", response_model=ImageOut, tags=["images"], dependencies=auth,
         summary="Replace all annotations of an image (original pixel coordinates)")
def save_annotations(image_id: int, body: AnnotationsSave, store: Store = Depends(get_store),
                     settings: Settings = Depends(get_settings)) -> ImageOut:
    image = get_image_or_404(store, image_id)
    known = {c["name"] for c in get_config_or_409(store, settings)["classes"]}
    boxes = []
    for index, item in enumerate(body.annotations):
        if item.class_name not in known:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"annotation #{index}: unknown class '{item.class_name}'")
        try:
            x1, y1, x2, y2 = normalize_box(item.x1, item.y1, item.x2, item.y2, image["width"], image["height"])
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"annotation #{index}: {exc}") from exc
        hard = item.type == "hard_negative"
        boxes.append({
            "class": item.class_name, "x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1),
            "type": item.type, "source": item.source,
            "source_confidence": item.source_confidence if hard else None, "source_model": item.source_model if hard else None,
        })
    return ImageOut(**store.save_annotations(image_id, boxes, body.mark_annotated))


@app.patch(f"{API_PREFIX}/images/{{image_id}}", response_model=ImageOut, tags=["images"], dependencies=auth,
           summary="Reopen an annotated image (annotations are kept)")
def update_image(image_id: int, body: StatusUpdate, store: Store = Depends(get_store)) -> ImageOut:
    get_image_or_404(store, image_id)
    return ImageOut(**store.set_status_open(image_id))


@app.post(f"{API_PREFIX}/images/{{image_id}}/detect", response_model=ImageOut, tags=["images"], dependencies=auth,
          summary="Check the image against the inference server and store its detections")
def detect(image_id: int, body: Optional[DetectRequest] = None, store: Store = Depends(get_store),
           settings: Settings = Depends(get_settings)) -> ImageOut:
    image = get_image_or_404(store, image_id)
    config = get_config_or_409(store, settings)
    if not config.get("inference_url"):
        raise HTTPException(status.HTTP_409_CONFLICT, "no inference server configured")
    confidence = body.confidence if body and body.confidence is not None else config["confidence"]
    url = f"{config['inference_url']}/api/v1/detect"
    try:
        with open(store.file_path(image), "rb") as f, inference_client() as client:
            res = client.post(url, data={"confidence": str(confidence)},
                              files={"image": (image["filename"] or "image", f, image["content_type"])})
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"inference server not reachable at {config['inference_url']}: "
                                                         f"{exc.__class__.__name__}") from exc
    if res.status_code != 200:
        try:
            detail = res.json().get("detail")
        except Exception:
            detail = None
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"inference server: HTTP {res.status_code}: {detail or res.text[:300]}")
    result = res.json()
    model = result.get("model") or {}
    detection = {
        "model_version": model.get("version") or "unknown",
        "input_width": int(model.get("input_width") or 0),
        "input_height": int(model.get("input_height") or 0),
        "confidence": float(result.get("confidence_threshold", confidence)),
        "inference_ms": result.get("inference_ms"),
        "detections": [{"class": d["class"], "confidence": d["confidence"], "bbox": d["bbox"]} for d in result.get("detections", [])],
        "created_at": utcnow(),
    }
    return ImageOut(**store.save_detection(image_id, detection))


@app.delete(f"{API_PREFIX}/images/{{image_id}}", status_code=status.HTTP_204_NO_CONTENT, tags=["images"], dependencies=auth,
            summary="Delete an image (also used by the training system after the import)")
def delete_image(image_id: int, store: Store = Depends(get_store)) -> Response:
    if not store.delete(image_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"image {image_id} not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# web UI (built from frontend/, see Dockerfile); registered last so the API routes take precedence
_static = get_settings().static_dir
if os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
