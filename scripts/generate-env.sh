#!/bin/sh
# Create .env with random secrets (does not overwrite an existing .env).
set -eu
cd "$(dirname "$0")/.."
if [ -f .env ]; then
    echo ".env already exists - not overwriting" >&2
    exit 1
fi
hex() { od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'; }
compose_file="docker-compose.yml"
if docker info 2>/dev/null | grep -qi 'runtimes:.*nvidia'; then
    compose_file="docker-compose.yml:docker-compose.gpu.yml"
    echo "NVIDIA runtime detected: training will use the GPU"
else
    echo "No NVIDIA runtime detected: training will run on CPU (slow)"
fi
sed \
    -e "s|^COMPOSE_FILE=.*|COMPOSE_FILE=$compose_file|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(hex 16)|" \
    -e "s|^GARAGE_RPC_SECRET=.*|GARAGE_RPC_SECRET=$(hex 32)|" \
    -e "s|^GARAGE_ADMIN_TOKEN=.*|GARAGE_ADMIN_TOKEN=$(hex 24)|" \
    -e "s|^S3_ACCESS_KEY_ID=.*|S3_ACCESS_KEY_ID=GK$(hex 12)|" \
    -e "s|^S3_SECRET_ACCESS_KEY=.*|S3_SECRET_ACCESS_KEY=$(hex 32)|" \
    .env.example > .env
chmod 600 .env
echo "created .env"
