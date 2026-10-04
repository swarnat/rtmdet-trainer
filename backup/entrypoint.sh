#!/bin/sh
# Runs as root only to make the backup directory usable for UID 10001 (the user of the worker
# and of the API container, which lists, downloads and deletes the backups), then starts odbackup.
set -eu
: "${BACKUP_DIR:=/backups}"
mkdir -p "$BACKUP_DIR"
if [ "$(id -u)" = "0" ]; then
    chown 10001:10001 "$BACKUP_DIR"
fi
exec /usr/local/bin/odbackup "$@"
