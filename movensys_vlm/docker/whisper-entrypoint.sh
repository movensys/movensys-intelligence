#!/bin/bash
set -e

MODEL_DIR=/models/${WHISPER_MODEL_NAME}
MODEL_DONE=$MODEL_DIR/.download_complete

if [ -f "$MODEL_DONE" ]; then
    echo "=== Model $HF_WHISPER_REPO already present, skipping download ==="
else
    echo "=== Downloading $HF_WHISPER_REPO ==="
    hf download "$HF_WHISPER_REPO" --local-dir "$MODEL_DIR"
    touch "$MODEL_DONE"
    echo "=== Download complete ==="
fi

exec "$@"
