# Client annotator (annotation service on a customer server). Build context: repository root
# (needs ./common, ./frontend and ./client-annotator)
#   make client-annotator   (= docker build -f client-annotator/Dockerfile -t swarnat/rtmdet-client-annotator:latest .)
# Images, annotations and the pushed configuration are kept in the volume mounted at /data.

# web UI: second entry point of the frontend project (frontend/client.html, shares the annotation components)
FROM node:22-alpine AS ui
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build:client && mv dist-client/client.html dist-client/index.html

FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY client-annotator/pyproject.toml client-annotator/requirements.lock client-annotator/
COPY common common
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib
print("\n".join(tomllib.load(open("client-annotator/pyproject.toml", "rb"))["project"]["dependencies"]))
PY
# odcore without its own dependencies: only images, geometry and download are used (no DB/S3)
RUN pip install -r /tmp/requirements.txt -c client-annotator/requirements.lock && pip install --no-deps ./common

COPY client-annotator/app /srv/client-annotator/app
COPY --from=ui /app/dist-client /srv/client-annotator/static

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && mkdir -p /data && chown -R app /data
USER app
WORKDIR /srv/client-annotator
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]

# Test image (not for production): make client-annotator-test
FROM base AS test
USER root
RUN pip install "pytest==8.3.4" -c /srv/client-annotator/requirements.lock
COPY tests/client_annotator /srv/tests/client_annotator
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "/srv/tests/client_annotator"]

# Production image (default target, must stay the last stage)
FROM base AS runtime
