# Build context: repository root (needs ./common and ./backend)
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY backend/pyproject.toml backend/requirements.lock backend/
COPY common common
# Install pinned dependencies first for better layer caching
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib
p = tomllib.load(open("backend/pyproject.toml", "rb"))["project"]
print("\n".join(p["dependencies"] + p["optional-dependencies"]["test"]))
PY
RUN pip install -r /tmp/requirements.txt -c backend/requirements.lock && pip install --no-deps ./common

COPY backend /srv/backend
COPY tests /srv/tests
RUN pip install --no-deps -e /srv/backend

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && mkdir -p /var/cache/od-models && chown app /var/cache/od-models
USER app
WORKDIR /srv/backend

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers"]
