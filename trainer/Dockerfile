# Build context: repository root (needs ./common and ./trainer)
# PyTorch 2.1.2 + CUDA 12.1 runtime, Python 3.10
FROM pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MMCV_VERSION=2.1.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Prebuilt mmcv (with CUDA ops) matching torch 2.1 / cu121
RUN pip install "mmcv==${MMCV_VERSION}" -f https://download.openmmlab.com/mmcv/dist/cu121/torch2.1/index.html

COPY trainer/pyproject.toml trainer/requirements.lock trainer/
COPY common common
RUN python - <<'PY' > /tmp/requirements.txt
import re
src = open("trainer/pyproject.toml").read()
deps = re.search(r"^dependencies = \[(.*?)^\]", src, re.S | re.M).group(1)
test = re.search(r"^test = \[(.*?)\]", src, re.M).group(1)
print("\n".join(re.findall(r'"([^"]+)"', deps + test)))
PY
# mmcv pulls in opencv-python (GUI build); keep only the headless variant
RUN pip install -r /tmp/requirements.txt -c trainer/requirements.lock \
    && pip uninstall -y opencv-python || true \
    && pip install --no-deps --force-reinstall opencv-python-headless==4.10.0.84 \
    && pip install --no-deps ./common

COPY trainer /srv/trainer
COPY tests /srv/tests
RUN pip install --no-deps -e /srv/trainer \
    && python -c "import mmcv, mmdet, mmengine, torch; print('torch', torch.__version__, 'mmcv', mmcv.__version__, 'mmdet', mmdet.__version__, 'mmengine', mmengine.__version__)"

WORKDIR /srv/trainer
CMD ["python", "-m", "trainer.worker"]
