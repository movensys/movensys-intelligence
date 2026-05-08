#!/bin/bash
set -e

MODEL_DIR=/models/${VLM_MODEL_NAME}
MODEL_DONE=$MODEL_DIR/.download_complete

if [ -f "$MODEL_DONE" ]; then
    echo "=== Model $HF_REPO_NAME already present, skipping download ==="
else
    echo "=== Downloading $HF_REPO_NAME ==="
    hf download "$HF_REPO_NAME" --local-dir "$MODEL_DIR"
    touch "$MODEL_DONE"
    echo "=== Download complete ==="
fi

exec "$@"
