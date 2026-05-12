#!/bin/bash
set -e

MODEL_DIR=/models/${WHISPER_MODEL_NAME}
MODEL_DONE=$MODEL_DIR/.download_complete

if [ -f "$MODEL_DONE" ]; then
    echo "=== Model $WHISPER_MODEL_REPO already present, skipping download ==="
else
    echo "=== Downloading $WHISPER_MODEL_REPO ==="
    hf download "$WHISPER_MODEL_REPO" --local-dir "$MODEL_DIR"
    touch "$MODEL_DONE"
    echo "=== Download complete ==="
fi

exec "$@"
