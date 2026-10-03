# Production detection API. Build context: repository root (needs ./common and ./inference-server)
#   make inference-server   (= docker build -f inference-server/Dockerfile -t swarnat/rtmdet-detection:latest .)
# The image contains NO model: it is installed at runtime via PUT /api/v1/model
# and kept in the volume mounted at /data.
FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY inference-server/pyproject.toml inference-server/requirements.lock inference-server/
COPY common common
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib
print("\n".join(tomllib.load(open("inference-server/pyproject.toml", "rb"))["project"]["dependencies"]))
PY
# odcore without its own dependencies: only geometry + OpenVINO detector are used (no DB/S3)
RUN pip install -r /tmp/requirements.txt -c inference-server/requirements.lock && pip install --no-deps ./common

COPY inference-server/app /srv/inference-server/app

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && mkdir -p /data/models && chown -R app /data
USER app
WORKDIR /srv/inference-server
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]

# Test image (not for production): make inference-server-test
FROM base AS test
USER root
RUN pip install "pytest==8.3.4" "httpx==0.28.1" -c /srv/inference-server/requirements.lock
COPY tests/inference_server /srv/tests/inference_server
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "/srv/tests/inference_server"]

# Production image (default target, must stay the last stage)
FROM base AS runtime
