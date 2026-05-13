#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# shellcheck disable=SC1091
source .venvs/vllm-intel/bin/activate

set -a
# shellcheck disable=SC1091
source docker/.env
set +a

exec vllm serve "${PROJECT_ROOT}/models/${VLM_MODEL_NAME}" \
  --served-model-name="${VLM_MODEL_NAME}" \
  --port=9000 \
  --max-model-len=2048 \
  --dtype=float16 \
  --gpu-memory-utilization=0.70 \
  --attention-backend=TRITON_ATTN \
  --enforce-eager \
  --limit-mm-per-prompt='{"image":1,"video":0,"audio":0}'
