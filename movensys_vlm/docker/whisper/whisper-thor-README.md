# Running Whisper STT on Jetson AGX Thor

Tested target:
- Jetson AGX Thor Developer Kit (Blackwell-gen iGPU, sm_110)
- JetPack 7.0 / L4T R38.2.0
- NVIDIA driver 580.00, CUDA 13.0
- Base container: `nvcr.io/nvidia/pytorch:26.04-py3` (matches the vLLM-Thor base — same CUDA/cuDNN runtime)
- HuggingFace `transformers` ASR pipeline running on the PyTorch already in the base image (sm_110 kernels prebuilt)

This service shares `server.py` with the Intel NPU build in the same directory. The backend is selected at startup by `WHISPER_BACKEND`, which is hard-pinned to `transformers` in [Dockerfile.whisper-thor](Dockerfile.whisper-thor). The HTTP surface (`POST /v1/audio/transcriptions`, `GET /v1/models`, `GET /health`) is identical to the NPU deployment, so OpenAI-compatible clients written against either box port over with just a `base_url` swap.

This service runs alongside the vLLM-Thor LLM server, which lives on **port 9000**. Whisper-Thor binds **port 9010**. Both share the Thor's unified memory pool — see [§ Coexistence with vLLM-Thor](#coexistence-with-vllm-thor) below.

## What this gives you

A small FastAPI process that wraps the HuggingFace `automatic-speech-recognition` pipeline on the iGPU and exposes:

- `POST /v1/audio/transcriptions` — multipart upload, OpenAI-compatible response (`{"text": "..."}` or plain text).
- `GET /v1/models` — minimal listing so OpenAI clients don't choke on startup.
- `GET /health` — liveness check, includes the active backend.

The default model is **`openai/whisper-large-v3`** — full Whisper large-v3 in HF format, run in `float16`. Thor has the memory headroom for the full model where Panther Lake doesn't, so we don't need the turbo+INT4 compromise the NPU service makes. To trade quality for latency, point `WHISPER_MODEL_REPO` at `openai/whisper-large-v3-turbo` or `distil-whisper/distil-large-v3`.

## 1. Prerequisites

### Power profile

Same as the vLLM-Thor service — Thor must be on MAXN, otherwise heavy model loads can hard-reboot the box:

```bash
sudo nvpmodel -m 0
sudo jetson_clocks
nvidia-smi   # should show "NVIDIA Thor"
```

### Docker access + NVIDIA runtime

```bash
sudo usermod -aG docker $USER
newgrp docker
docker info | grep -i runtime    # nvidia runtime should be listed
```

If you've already brought up vLLM-Thor on this machine, this is already done.

### Disk space

The base PyTorch image is large (~10 GB). Reserve another ~5 GB under `~/.cache/huggingface` and `~/models` for the Whisper weights (~3 GB for full large-v3 fp16, ~1.5 GB for the turbo or distil variants).

## 2. Build the image

```bash
cd movensys_vlm/docker/whisper
docker compose -f whisper-thor-compose.yml build
```

The build is short — it just installs `transformers` and a few audio deps on top of the published Jetson PyTorch image. Nothing is compiled from source.

## 3. (Optional) Pre-download the model

`transformers` will download on first start, but you can prime the cache:

```bash
mkdir -p ~/models
pip install -U "huggingface_hub[cli]"
hf download openai/whisper-large-v3 \
  --local-dir ~/models/whisper-large-v3
```

The compose file mounts `~/models` at `/models`, and `server.py` checks `WHISPER_MODEL_DIR` first before falling back to a Hub download.

## 4. Run as a service

```bash
cd movensys_vlm/docker/whisper

docker compose -f whisper-thor-compose.yml up -d
docker compose -f whisper-thor-compose.yml logs -f
docker compose -f whisper-thor-compose.yml ps
docker compose -f whisper-thor-compose.yml down
```

First request loads CUDA kernels and warms the model — expect a few seconds of latency, then real-time-or-better transcription on subsequent calls.

### Coexistence with vLLM-Thor

This service binds **port 9010**; the vLLM-Thor compose binds **9000**. Bring them up in either order:

```bash
docker compose -f ../vllm/vllm-thor-compose.yml up -d   # iGPU LLM, port 9000
docker compose -f whisper-thor-compose.yml up -d        # iGPU STT, port 9010
```

Both services share the iGPU and Thor's unified memory pool. The default vLLM-Thor compose pins `--gpu-memory-utilization=0.3` precisely to leave headroom for sidecar workloads like this one. If you raise that value, validate that whisper-thor still loads — large-v3 fp16 needs ~3 GB of GPU memory at runtime.

## 5. Test the endpoint

```bash
# Health
curl http://localhost:9010/health

# Transcribe a wav (any sample rate; we resample to 16 kHz internally)
curl -X POST http://localhost:9010/v1/audio/transcriptions \
  -F "file=@sample.wav" \
  -F "language=en" \
  -F "response_format=json"
```

From the OpenAI Python client:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:9010/v1", api_key="none")
with open("sample.wav", "rb") as f:
    out = client.audio.transcriptions.create(
        model="whisper-large-v3",
        file=f,
        language="en",
    )
print(out.text)
```

## 6. Configuration

All knobs are environment variables, settable in `.env` or the compose file:

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_BACKEND` | `transformers` | Pinned in the Dockerfile; do not override. |
| `WHISPER_MODEL_REPO` | `openai/whisper-large-v3` | HF repo to pull if `WHISPER_MODEL_DIR` is empty. |
| `WHISPER_MODEL_DIR` | `/models/whisper-large-v3` | Local model directory to load from (preferred). |
| `WHISPER_DEVICE` | `cuda` | Pass `cpu` to bypass the iGPU for debugging. |
| `WHISPER_TORCH_DTYPE` | `float16` | `float16`, `bfloat16`, or `float32`. fp16 is the right default on Blackwell; bf16 if you hit numerical issues. |
| `WHISPER_DEFAULT_LANGUAGE` | (auto-detect) | Language hint applied when the request omits one (`en`, `ko`, …). |
| `WHISPER_CHUNK_LENGTH_S` | `30` | Audio chunking window for the HF pipeline. 30s matches Whisper's native window; lower for lower-latency streaming-style use. |

## 7. Troubleshooting

**`CUDA failed with error CUDA driver version is insufficient`** or `libcudnn.so` not found inside the container. The image expects to run with `runtime: nvidia` (set in the compose file). Confirm with `docker info | grep -i runtime`. If the runtime is missing, install the NVIDIA Container Toolkit on the host.

**System reboots during model load.** Same root causes as vLLM-Thor — almost always power or memory. Confirm MAXN, drop to a smaller model (`whisper-large-v3-turbo` or `distil-whisper/distil-large-v3`), switch `WHISPER_TORCH_DTYPE` to `float16` if it's currently `float32`, or lower vLLM's `--gpu-memory-utilization` to free headroom.

**`Could not load model … with any of the following classes`** during startup. The repo you pointed `WHISPER_MODEL_REPO` at isn't a Whisper checkpoint in HF format. The transformers backend wants `openai/whisper-*` or `distil-whisper/*` repos — *not* the OpenVINO IR repos used by the NPU build, and *not* CTranslate2 repos under `Systran/faster-whisper-*`.

**Garbled output / wrong language.** Pass `language=` in the request, or set `WHISPER_DEFAULT_LANGUAGE` in `.env`. Without a hint Whisper auto-detects per request and short clips can mis-route.

**Slow first request.** Expected — CUDA kernels and the model graph load on first use. Subsequent requests should be fast.

## 8. Notes on model variants

| Variant | Memory (fp16) | Quality | Notes |
|---|---|---|---|
| `openai/whisper-large-v3` | ~3.0 GB | Best | Default. |
| `openai/whisper-large-v3-turbo` | ~1.6 GB | Near-best for en/ko, weaker on low-resource langs | 4-decoder-layer distillation; ~5× faster decoder. |
| `distil-whisper/distil-large-v3` | ~1.5 GB | English-focused, near-large WER on en | Best for English-only sidecar use. |

For the Thor sidecar use case (continuous-listen STT alongside a VLM), `whisper-large-v3-turbo` is usually the sweet spot — it leaves the LLM more memory and decodes well above real-time. Stay on full `large-v3` if you need the absolute best WER and have the memory budget after vLLM is loaded.

## 9. Why transformers, not faster-whisper or vLLM

- The Intel-NPU sibling uses OpenVINO GenAI because that's the only mature Whisper path on the NPU; it doesn't transfer to CUDA.
- `faster-whisper` (CTranslate2) is normally the high-perf Whisper runtime on CUDA, but ctranslate2's PyPI wheels for arm64 are compiled CPU-only — installing it on Thor silently runs the model on CPU. Building ctranslate2 from source against CUDA 13 / sm_110 is possible but adds a long compile step and a per-JetPack maintenance burden. We can revisit if STT throughput becomes a bottleneck.
- vLLM has a Whisper path, but it pulls in the full vLLM scheduler for what is fundamentally a single-stream encoder-decoder workload. Running it as a sidecar to the *actual* vLLM LLM server would mean two scheduler/engines competing for the same iGPU.
- HuggingFace `transformers` rides on the PyTorch already in the Jetson base image, which has sm_110 kernels prebuilt. Slower than CTranslate2-on-CUDA *would* be, but fast enough for sidecar STT and zero source-build cost.
