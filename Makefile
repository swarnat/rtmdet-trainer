# Build helpers
#   make inference-server              build the production detection image (no model inside)
#   make inference-server TAG=1.0.0    ... with an explicit version tag
#   make inference-server-test         run the inference server tests in Docker
#   make inference-server-push         build and push to the registry (docker login first)

INFERENCE_IMAGE ?= swarnat/rtmdet-detection
TAG ?= latest

.PHONY: help inference-server make-inference-server inference-server-test inference-server-push

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
