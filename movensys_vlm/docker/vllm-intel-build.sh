#!/usr/bin/env bash
set -euo pipefail

# Resolve paths relative to this script so it works from any cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
  sudo snap install astral-uv --classic
fi

# 2. Python 3.12 venv (idempotent)
if [ ! -d ".venvs/vllm-intel" ]; then
  uv venv --python 3.12 --seed --managed-python .venvs/vllm-intel
fi
# shellcheck disable=SC1091
source .venvs/vllm-intel/bin/activate

# 3. vLLM source (clone once, then pin)
if [ ! -d "vllm" ]; then
  git clone https://github.com/vllm-project/vllm.git
fi
cd vllm
git checkout v0.20.0

# 4. Build vLLM for XPU
pip install --upgrade pip
pip install -v -r requirements/xpu.txt
pip uninstall -y triton triton-xpu
pip install triton-xpu==3.7.0 --extra-index-url https://download.pytorch.org/whl/xpu
VLLM_TARGET_DEVICE=xpu pip install --no-build-isolation -e . -v

# 5. Hugging Face CLI (for the download step)
pip install "huggingface_hub[cli]"

# 6. Download the model (same idempotent pattern as docker/vllm-entrypoint.sh)
cd "${PROJECT_ROOT}"
set -a
# shellcheck disable=SC1091
source docker/.env
set +a

MODEL_DIR="${PROJECT_ROOT}/models/${VLM_MODEL_NAME}"
if [ -f "${MODEL_DIR}/.download_complete" ]; then
  echo "=== Model ${HF_VLM_REPO} already present, skipping download ==="
else
  echo "=== Downloading ${HF_VLM_REPO} ==="
  hf download "${HF_VLM_REPO}" --local-dir "${MODEL_DIR}"
  touch "${MODEL_DIR}/.download_complete"
  echo "=== Download complete ==="
fi
