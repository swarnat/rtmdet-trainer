# Build helpers
#   make inference-server              build the production detection image (no model inside)
#   make inference-server TAG=1.0.0    ... with an explicit version tag
#   make inference-server-test         run the inference server tests in Docker
#   make inference-server-push         build and push to the registry (docker login first)
#   make client-annotator              build the client annotator image (annotation service on a customer server)
#   make client-annotator TAG=1.0.0    ... with an explicit version tag
#   make client-annotator-test         run the client annotator tests in Docker
#   make client-annotator-push         build and push to the registry (docker login first)
#   make backup                        full backup now (database + images + models + configuration) into BACKUP_PATH
#   make backup-list                   list backups
#   make backup-verify FILE=<name>     read and check a backup file completely
#   make restore FILE=<name>           REPLACE everything with a backup (stops api/trainer/frontend, starts them again)
#   make backup-test                   run the backup tests in Docker
#   make release                       build and push backend, frontend, trainer, backup (asks for the version, also tags latest)
#   make release VERSION=1.2.0         ... without asking
#   make release-backend / -frontend / -trainer / -backup   only one of the images

INFERENCE_IMAGE ?= swarnat/rtmdet-detection
CLIENT_ANNOTATOR_IMAGE ?= swarnat/rtmdet-client-annotator
BACKEND_IMAGE ?= swarnat/rtmdet-annotations-backend
FRONTEND_IMAGE ?= swarnat/rtmdet-annotations-frontend
TRAINER_IMAGE ?= swarnat/rtmdet-annotations-trainer
BACKUP_IMAGE ?= swarnat/rtmdet-annotations-backup
TAG ?= latest

.PHONY: help inference-server make-inference-server inference-server-test inference-server-push \
	client-annotator client-annotator-test client-annotator-push \
	backup backup-list backup-verify restore backup-test release release-backend release-frontend release-trainer release-backup

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

client-annotator:
	docker build -f client-annotator/Dockerfile -t $(CLIENT_ANNOTATOR_IMAGE):$(TAG) .

client-annotator-test:
	docker build -f client-annotator/Dockerfile --target test -t $(CLIENT_ANNOTATOR_IMAGE):test .
	docker run --rm $(CLIENT_ANNOTATOR_IMAGE):test

client-annotator-push: client-annotator
	docker push $(CLIENT_ANNOTATOR_IMAGE):$(TAG)

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

# -- release: backend, frontend, trainer and backup images to Docker Hub (docker login first) ------------------
# VERSION is asked for when not given; every release is also tagged and pushed as latest.
# asked only for the release targets, once per make call (from the terminal, stderr keeps the prompt visible)
ifneq ($(filter release%,$(MAKECMDGOALS)),)
ifeq ($(strip $(VERSION)),)
VERSION := $(shell read -p "Version (e.g. 1.2.0): " v </dev/tty >&2 && echo "$$v")
endif
endif

release: release-backend release-frontend release-trainer release-backup

release-backend: _check-version
	docker build -f backend/Dockerfile -t $(BACKEND_IMAGE):$(VERSION) -t $(BACKEND_IMAGE):latest .
	docker push $(BACKEND_IMAGE):$(VERSION)
	docker push $(BACKEND_IMAGE):latest

release-frontend: _check-version
	docker build -t $(FRONTEND_IMAGE):$(VERSION) -t $(FRONTEND_IMAGE):latest frontend
	docker push $(FRONTEND_IMAGE):$(VERSION)
	docker push $(FRONTEND_IMAGE):latest

release-trainer: _check-version
	docker build -f trainer/Dockerfile -t $(TRAINER_IMAGE):$(VERSION) -t $(TRAINER_IMAGE):latest .
	docker push $(TRAINER_IMAGE):$(VERSION)
	docker push $(TRAINER_IMAGE):latest

release-backup: _check-version
	docker build -f backup/Dockerfile -t $(BACKUP_IMAGE):$(VERSION) -t $(BACKUP_IMAGE):latest .
	docker push $(BACKUP_IMAGE):$(VERSION)
	docker push $(BACKUP_IMAGE):latest

_check-version:
	@test -n "$(VERSION)" || { echo "no version given"; exit 1; }
	@test "$(VERSION)" != latest || { echo "version must not be 'latest' (it is always pushed as well)"; exit 1; }
	@echo "release version $(VERSION)"
