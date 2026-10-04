# Backup service: pg_dump/pg_restore of the same major version as the database + Python CLI/worker.
# Build context: repository root (needs ./backup and the Alembic revisions of ./backend)
FROM postgres:16-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BACKUP_DIR=/backups \
    ALEMBIC_VERSIONS_DIR=/srv/alembic-versions

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

WORKDIR /srv/backup
COPY backup/pyproject.toml backup/requirements.lock ./
RUN /opt/venv/bin/python - <<'PY' > /tmp/requirements.txt
import tomllib
print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]))
PY
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt -c requirements.lock
COPY backup/odbackup ./odbackup
RUN /opt/venv/bin/pip install --no-deps .
# schema revisions known to this version (restore refuses backups from a newer schema)
COPY backend/alembic/versions /srv/alembic-versions
COPY backup/entrypoint.sh /usr/local/bin/odbackup-entrypoint
# `odbackup` on the PATH, also for `docker compose exec backup odbackup …` (switches to UID 10001)
COPY backup/odbackup.sh /usr/local/bin/odbackup
RUN chmod +x /usr/local/bin/odbackup-entrypoint /usr/local/bin/odbackup

VOLUME ["/backups"]
ENTRYPOINT ["odbackup-entrypoint"]
CMD ["worker"]

# Test image: make backup-test
FROM base AS test
RUN /opt/venv/bin/pip install "pytest==8.3.4" -c /srv/backup/requirements.lock
COPY tests/backup /srv/tests/backup
ENTRYPOINT []
CMD ["/opt/venv/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "/srv/tests/backup"]

# Production image (default target, must stay the last stage)
FROM base AS runtime
