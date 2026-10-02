#!/bin/sh
# Idempotent Garage initialisation via the admin API (v1):
#   1. assign a layout role to the (single) node and apply the layout
#   2. import the S3 access key given in S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY
#   3. create the buckets and grant the key read/write/owner on them
# Safe to run on every start: existing state is detected and left untouched.
set -eu

: "${GARAGE_ADMIN_URL:=http://garage:3903}"
: "${GARAGE_ADMIN_TOKEN:?GARAGE_ADMIN_TOKEN is required}"
: "${S3_ACCESS_KEY_ID:?S3_ACCESS_KEY_ID is required}"
: "${S3_SECRET_ACCESS_KEY:?S3_SECRET_ACCESS_KEY is required}"
: "${GARAGE_ZONE:=dc1}"
: "${GARAGE_CAPACITY_BYTES:=100000000000}"
: "${GARAGE_KEY_NAME:=object-detection}"
BUCKETS="${S3_BUCKET_IMAGES:-training-images} ${S3_BUCKET_DATASETS:-datasets} ${S3_BUCKET_MODELS:-models}"

log() { echo "[garage-init] $*"; }

# api METHOD PATH [JSON]  -> prints body, returns non-zero on HTTP >= 400
api() {
    method=$1; path=$2; data=${3:-}
    if [ -n "$data" ]; then
        resp=$(curl -sS -w '\n%{http_code}' -X "$method" -H "Authorization: Bearer $GARAGE_ADMIN_TOKEN" \
            -H 'Content-Type: application/json' --data "$data" "$GARAGE_ADMIN_URL$path")
    else
        resp=$(curl -sS -w '\n%{http_code}' -X "$method" -H "Authorization: Bearer $GARAGE_ADMIN_TOKEN" "$GARAGE_ADMIN_URL$path")
    fi
    code=$(printf '%s' "$resp" | tail -n1)
    printf '%s' "$resp" | sed '$d'
    [ "$code" -lt 400 ]
}

log "waiting for admin API at $GARAGE_ADMIN_URL"
i=0
until status=$(api GET /v1/status 2>/dev/null); do
    i=$((i + 1))
    [ "$i" -gt 60 ] && { log "admin API not reachable"; exit 1; }
    sleep 2
done
NODE_ID=$(printf '%s' "$status" | jq -r '.node')
log "node id: $NODE_ID"

# 1) layout
layout=$(api GET /v1/layout)
has_role=$(printf '%s' "$layout" | jq --arg id "$NODE_ID" '[.roles[] | select(.id == $id)] | length')
if [ "$has_role" = "0" ]; then
    log "assigning layout role (zone $GARAGE_ZONE, capacity $GARAGE_CAPACITY_BYTES bytes)"
    api POST /v1/layout "[{\"id\":\"$NODE_ID\",\"zone\":\"$GARAGE_ZONE\",\"capacity\":$GARAGE_CAPACITY_BYTES,\"tags\":[\"local\"]}]" >/dev/null
    version=$(api GET /v1/layout | jq '.version')
    api POST /v1/layout/apply "{\"version\":$((version + 1))}" >/dev/null
    log "layout version $((version + 1)) applied"
else
    log "layout already configured"
fi

# Wait until the cluster is healthy (layout propagated)
i=0
until [ "$(api GET /v1/health 2>/dev/null | jq -r '.status' 2>/dev/null)" = "healthy" ]; do
    i=$((i + 1))
    [ "$i" -gt 60 ] && { log "cluster did not become healthy"; exit 1; }
    sleep 2
done

# 2) access key
if api GET "/v1/key?id=$S3_ACCESS_KEY_ID" >/dev/null 2>&1; then
    log "access key $S3_ACCESS_KEY_ID already present"
else
    log "importing access key $S3_ACCESS_KEY_ID"
    api POST /v1/key/import "{\"accessKeyId\":\"$S3_ACCESS_KEY_ID\",\"secretAccessKey\":\"$S3_SECRET_ACCESS_KEY\",\"name\":\"$GARAGE_KEY_NAME\"}" >/dev/null
fi

# 3) buckets + permissions
for bucket in $BUCKETS; do
    if info=$(api GET "/v1/bucket?globalAlias=$bucket" 2>/dev/null); then
        log "bucket $bucket exists"
    else
        log "creating bucket $bucket"
        info=$(api POST /v1/bucket "{\"globalAlias\":\"$bucket\"}")
    fi
    bucket_id=$(printf '%s' "$info" | jq -r '.id')
    api POST /v1/bucket/allow "{\"bucketId\":\"$bucket_id\",\"accessKeyId\":\"$S3_ACCESS_KEY_ID\",\"permissions\":{\"read\":true,\"write\":true,\"owner\":true}}" >/dev/null
done

log "done"
