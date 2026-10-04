# Build helpers
#   make inference-server              build the production detection image (no model inside)
#   make inference-server TAG=1.0.0    ... with an explicit version tag
#   make inference-server-test         run the inference server tests in Docker
#   make inference-server-push         build and push to the registry (docker login first)
#   make backup                        full backup now (database + images + models + configuration) into BACKUP_PATH
#   make backup-list                   list backups
#   make backup-verify FILE=<name>     read and check a backup file completely
#   make restore FILE=<name>           REPLACE everything with a backup (stops api/trainer/frontend, starts them again)
#   make backup-test                   run the backup tests in Docker

INFERENCE_IMAGE ?= swarnat/rtmdet-detection
TAG ?= latest

.PHONY: help inference-server make-inference-server inference-server-test inference-server-push \
	backup backup-list backup-verify restore backup-test

help:
	@grep -E '^#   make' $(MAKEFILE_LIST) | sed 's/^#   //'

inference-server:
	docker build -f inference-server/Dockerfile -t $(INFERENCE_IMAGE):$(TAG) .

# alias
make-inference-server: inference-server

inference-server-test:
	docker build -f inference-server/Dockerfile --target test -t $(INFERENCE_IMAGE):test .
	docker run --rm $(INFERENCE_IMAGE):test

inference-server-push: inference-server
	docker push $(INFERENCE_IMAGE):$(TAG)

# -- backup / restore (docker compose uses COMPOSE_FILE from .env) -------------------------
# All commands run inside the running "backup" service (docker compose exec).
# FILE: name of a backup in BACKUP_PATH, with or without .tar, or a path to it (only the file name is used)
FILE ?=
RESTORE_ARGS ?=

backup:
	docker compose exec backup odbackup create

backup-list:
	docker compose exec backup odbackup list

backup-verify:
	@test -n "$(FILE)" || { echo "usage: make backup-verify FILE=<backup name>"; exit 1; }
	docker compose exec backup odbackup verify $(notdir $(FILE))

restore:
	@test -n "$(FILE)" || { echo "usage: make restore FILE=<backup name>   (see: make backup-list)"; exit 1; }
	docker compose up -d backup
	docker compose stop api trainer frontend
	docker compose exec backup odbackup restore $(notdir $(FILE)) $(RESTORE_ARGS); status=$$?; \
	docker compose up -d; exit $$status

backup-test:
	docker build -f backup/Dockerfile --target test -t object-detection/backup:test .
	docker run --rm object-detection/backup:test
