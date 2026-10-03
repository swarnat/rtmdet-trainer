"""FastAPI application: inference, training data, training jobs and model registry."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import annotations, batch_tests, classes, detect, images, models, settings, training
from app.core.config import get_settings

API_PREFIX = "/api/v1"

logging.basicConfig(
    level=get_settings().log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.core.database import get_sessionmaker
    from app.services.batch_test import fail_interrupted_batches

    try:
        with get_sessionmaker()() as session:
            if n := fail_interrupted_batches(session):
                log.warning("marked %d interrupted batch test(s) as failed", n)
    except Exception:  # DB not reachable yet: health check reports it
        log.exception("could not clean up batch tests on startup")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Object Detection Training & Inference",
    version="0.1.0",
    description=(
        "Detects configurable object classes (initially **person**, **bicycle**, **vehicle**) in 16:9 camera "
        "images with an RTMDet-S model "
        "running on OpenVINO (CPU). Provides training-image management, annotation storage, "
        "manually started training runs and a model registry with production/candidate/archived versions."
    ),
    openapi_url=f"{API_PREFIX}/openapi.json",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
)

origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


health_router = APIRouter(tags=["health"])


@health_router.get("/health", summary="Liveness/readiness of the API and its dependencies")
def health() -> JSONResponse:
    from app.core.database import get_engine
    from app.core.queue import get_redis
    from app.core.s3 import get_storage

    checks: dict[str, str] = {}
    for name, check in (
        ("database", lambda: get_engine().connect().execute(text("SELECT 1")).close()),
        ("redis", lambda: get_redis().ping()),
        ("s3", lambda: get_storage().check_buckets()),
    ):
        try:
            check()
            checks[name] = "ok"
        except Exception as exc:  # report, don't raise
            checks[name] = f"error: {exc.__class__.__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", "checks": checks})


for router in (health_router, detect.router, batch_tests.router, classes.router, images.router, annotations.router, training.router, models.router, settings.router):
    app.include_router(router, prefix=API_PREFIX)
