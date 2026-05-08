#!/bin/bash
set -e

MODEL_REPO=${VLM_MODEL_REPO:-google/gemma-4-E4B-it}
MODEL_NAME=$(basename "$MODEL_REPO")
MODEL_DIR=/models/$MODEL_NAME

if [ ! -d "$MODEL_DIR" ]; then
    echo "=== Downloading $MODEL_REPO ==="
    huggingface-cli download "$MODEL_REPO" --local-dir "$MODEL_DIR"
    echo "=== Download complete ==="
fi

exec "$@"
