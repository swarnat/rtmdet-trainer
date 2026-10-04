#!/bin/sh
# Command line entry, also for `docker compose exec backup odbackup …` (exec bypasses the entrypoint and
# runs as root): always run as UID 10001 like the worker, so the lock file and backups stay shared.
APP_UID=10001
if [ "$(id -u)" = "0" ]; then
    exec gosu "$APP_UID:$APP_UID" env HOME=/tmp /opt/venv/bin/odbackup "$@"
fi
exec /opt/venv/bin/odbackup "$@"
