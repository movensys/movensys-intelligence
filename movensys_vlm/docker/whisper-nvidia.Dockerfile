# Whisper STT on Jetson AGX Thor (Blackwell-gen iGPU, sm_110) via transformers.
#
# Strategy: build on the same NVIDIA Jetson container family used by the Thor
# vLLM image — it ships CUDA 13 + a PyTorch with sm_110 kernels prebuilt. We
# layer HuggingFace transformers on top and let its `automatic-speech-recognition`
# pipeline drive Whisper through the existing torch.
#
# Why not faster-whisper: ctranslate2's PyPI wheels for arm64 are compiled
# CPU-only (no CUDA), so on Thor faster-whisper silently falls back to CPU.
# Building ctranslate2 from source against CUDA 13 / sm_110 is possible but
# adds a ~15 min compile step and a maintenance burden every time JetPack
# moves. transformers + torch is the path of least resistance: universal
# wheels, sm_110 kernels already present in the base.
#
# Shares server.py with the NPU build — backend is selected by WHISPER_BACKEND
# at startup, set to `transformers` here. See server.py for the contract.

FROM nvcr.io/nvidia/pytorch:26.04-py3

ENV PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface \
    DEBIAN_FRONTEND=noninteractive \
    WHISPER_BACKEND=transformers

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
        "transformers>=4.45" \
        "accelerate>=0.34" \
        "huggingface_hub[cli]>=0.24" \
        "librosa>=0.10" \
        "soundfile>=0.12" \
        "fastapi>=0.110" \
        "uvicorn[standard]>=0.30" \
        "python-multipart>=0.0.9"

WORKDIR /app
COPY whisper_server.py /app/whisper_server.py
COPY docker/whisper-entrypoint.sh /whisper-entrypoint.sh
RUN chmod +x /whisper-entrypoint.sh

EXPOSE 9010

ENTRYPOINT ["/whisper-entrypoint.sh"]
