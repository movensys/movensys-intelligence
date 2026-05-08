#!/bin/bash
set -e

MODEL_NAME=google/gemma-4-E4B-it
MODEL_DIR=/models/gemma-4-E4B-it
MODEL_DONE=$MODEL_DIR/.download_complete

if [ -f "$MODEL_DONE" ]; then
    echo "=== Model $MODEL_NAME already present, skipping download ==="
else
    echo "=== Downloading $MODEL_NAME ==="
    hf download "$MODEL_NAME" --local-dir "$MODEL_DIR"
    touch "$MODEL_DONE"
    echo "=== Download complete ==="
fi

exec "$@"
