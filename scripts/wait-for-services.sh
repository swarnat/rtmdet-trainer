#!/bin/sh
# Wait until the stack is up: API healthy (DB, Redis, S3 reachable) and frontend serving.
#   ./scripts/wait-for-services.sh [base-url] [timeout-seconds]
set -eu
BASE_URL="${1:-http://localhost:${FRONTEND_PORT:-8080}}"
TIMEOUT="${2:-300}"
start=$(date +%s)
printf 'waiting for %s ' "$BASE_URL"
until curl -fsS "$BASE_URL/api/v1/health" >/dev/null 2>&1; do
    if [ $(( $(date +%s) - start )) -gt "$TIMEOUT" ]; then
        echo " timeout"
        curl -sS "$BASE_URL/api/v1/health" || true
        exit 1
    fi
    printf '.'
    sleep 3
done
echo " ok"
curl -fsS "$BASE_URL/api/v1/health"
echo
