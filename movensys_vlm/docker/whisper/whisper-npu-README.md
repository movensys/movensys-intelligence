# Running Whisper STT on the Intel NPU (Panther Lake)

Tested target:
- Intel Core Ultra (Panther Lake) with on-die NPU, exposed as `/dev/accel/accel0`
- Ubuntu 24.04
- Intel `intel_vpu` kernel driver loaded on the host
- OpenVINO 2026.0 runtime + OpenVINO GenAI 2026.0 inside the container

This service runs alongside the vLLM XPU server (which uses the Panther Lake **iGPU**). The NPU and the iGPU are independent compute blocks on Core Ultra, so the two services can coexist without fighting for the same engine — they only share system RAM and memory bandwidth.

## What this gives you

A small FastAPI process that wraps `openvino_genai.WhisperPipeline` on the NPU and exposes:

- `POST /v1/audio/transcriptions` — multipart upload, OpenAI-compatible response shape (`{"text": "..."}` or plain text).
- `GET /v1/models` — minimal listing so OpenAI clients don't choke on startup.
- `GET /health` — liveness check.

The default model is **`movensys/whisper-large-v3-turbo-fp16-ov-npu`**: large-v3 *turbo* (the distilled 4-decoder-layer variant of large-v3) re-exported to OpenVINO IR with the modern stateful API (single-file decoder + `beam_idx` input) that OpenVINO 2026's NPU plugin requires. fp16 weights, ~1.6 GB. See [§ Why a movensys-hosted IR](#why-a-movensys-hosted-ir) below for why we don't use the older community NPU IRs.

## 1. Prerequisites

### Intel NPU driver on the host

Panther Lake's NPU is driven by the in-tree `intel_vpu` module on recent kernels. Verify:

```bash
lsmod | grep intel_vpu
ls -l /dev/accel/accel0          # should exist; owned by root:render typically
dmesg | grep -i 'intel_vpu\|npu' # firmware load messages
```

If `/dev/accel/accel0` is missing, install Intel's NPU user-mode driver / firmware package and reboot. See the [Intel NPU driver releases](https://github.com/intel/linux-npu-driver/releases) for matching `intel-driver-compiler-npu` / `intel-fw-npu` / `intel-level-zero-npu` packages and confirm the firmware version your kernel expects.

Add yourself to the group that owns `/dev/accel/accel0` (usually `render` on Ubuntu 24.04):

```bash
ls -l /dev/accel/accel0           # note the group
sudo usermod -aG render $USER
newgrp render
```

If `accel0` is owned by a non-`render` group on your host, set `RENDER_GID` in `.env` to that group's GID — the compose file injects it into the container so the non-root process can open the device:

```bash
echo "RENDER_GID=$(getent group render | cut -d: -f3)" >> .env
```

### Disk space

The image is small (~2 GB) since OpenVINO runtime is the only heavyweight dep. Reserve ~5 GB under `~/.cache/huggingface`, `~/models`, and `~/.cache/ze_intel_npu_cache` (NPU compile cache) for the Whisper IR files (~1.6 GB for the fp16 turbo variant) and a few hundred MB of cached compiled blobs.

## 2. Build the image

```bash
cd movensys_vlm/docker/whisper
docker compose -f whisper-npu-compose.yml build
```

Unlike the vLLM XPU image this build does not compile anything from source — it just installs OpenVINO wheels on top of the published `openvino/ubuntu24_runtime:2026.0.0` image, so a first build is a few minutes, not an hour.

## 3. (Optional) Pre-download the model

The server downloads the model on first start, but you can prime the cache to avoid a slow first boot:

```bash
mkdir -p ~/models
pip install -U "huggingface_hub[cli]"
hf download movensys/whisper-large-v3-turbo-fp16-ov-npu \
  --local-dir ~/models/whisper-large-v3-turbo-fp16-ov-npu
```

The compose file mounts `~/models` at `/models` inside the container, and `server.py` checks `WHISPER_MODEL_DIR` first before falling back to a Hub download.

## 4. Run as a service

```bash
cd movensys_vlm/docker/whisper

docker compose -f whisper-npu-compose.yml up -d
docker compose -f whisper-npu-compose.yml logs -f
docker compose -f whisper-npu-compose.yml ps
docker compose -f whisper-npu-compose.yml down
```

The first start triggers an NPU compile of the Whisper graph. **Cold-start compile is several minutes** (≈9 min on Panther Lake for large-v3-turbo); the compiled blobs are written to `~/.cache/ze_intel_npu_cache` (Level Zero NPU cache, mounted into the container). Subsequent restarts hit the cache and bind in seconds. Tail the logs and wait for `Uvicorn running on http://0.0.0.0:9010` before issuing requests — until then, `curl` will see "connection reset" because nothing is bound yet.

### Coexistence with vLLM-XPU

This service binds **port 9010** (bridge networking, `9010:9010`); the vLLM XPU compose binds **9000**. Bring them up in either order:

```bash
docker compose -f ../vllm/vllm-xpu-compose.yml up -d   # iGPU, port 9000
docker compose -f whisper-npu-compose.yml up -d        # NPU,  port 9010
```

Memory note: the NPU has a small amount of dedicated SRAM but spills weights/activations to system RAM, the same pool the iGPU's KV cache lives in. Budget conservatively if you also push `--max-model-len` high on the vLLM side.

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

From the OpenAI Python client (works out of the box because we honor the same multipart shape):

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:9010/v1", api_key="none")
with open("sample.wav", "rb") as f:
    out = client.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=f,
        language="en",
    )
print(out.text)
```

## 6. Configuration

All knobs are environment variables, settable in `.env` or the compose file:

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_MODEL_REPO` | `movensys/whisper-large-v3-turbo-fp16-ov-npu` | HF repo to pull if `WHISPER_MODEL_DIR` is empty. |
| `WHISPER_MODEL_DIR` | `/models/whisper-large-v3-turbo-fp16-ov-npu` | Local IR directory to load from (preferred over Hub download). |
| `WHISPER_DEVICE` | `NPU` | OpenVINO device. Set to `CPU` or `GPU` to bypass the NPU for debugging. |
| `WHISPER_DEFAULT_LANGUAGE` | (auto-detect) | Language hint applied when the request omits one (`en`, `ko`, …). |
| `WHISPER_MAX_NEW_TOKENS` | `448` | Decoder cap per request — Whisper's per-30s-window limit. |
| `RENDER_GID` | `992` | Host GID of the group owning `/dev/accel/accel0`. Override via `.env` if `getent group render` shows a different GID. |

## 7. Troubleshooting

**`Failed to compile model on NPU` / `device NPU not found`.** Host driver isn't loaded or the container can't see the device. Inside the container, `ls /dev/accel` should list `accel0`. On the host, check `lsmod | grep intel_vpu` and `dmesg | tail`. If the device is there but read-only inside the container, `RENDER_GID` is wrong — fix it from `getent group render`.

**Container is up but `curl /health` returns "Connection reset by peer".** First-run NPU compile is in progress and Uvicorn hasn't bound 9010 yet. Watch `docker compose logs -f` for `Uvicorn running on http://0.0.0.0:9010`. Cold compile of large-v3-turbo on Panther Lake is ~9 minutes; the cache under `~/.cache/ze_intel_npu_cache` makes subsequent restarts near-instant. If every restart is slow, the cache volume isn't persisting — confirm the host directory exists and is writable.

**`Stateful models without 'beam_idx' input are not supported in StatefulToStateless transformation`.** You're pointing at an older OpenVINO IR (e.g. one of the FluidInference NPU repos) that was exported with the legacy two-file decoder shape. OV 2026's NPU plugin requires the modern stateful export with a `beam_idx` input. The default `movensys/whisper-large-v3-turbo-fp16-ov-npu` was re-exported for OV 2026; if you're overriding the model, make sure your IR has only `openvino_decoder_model.xml` (no `_with_past`) and exposes `beam_idx` as a decoder input.

**OOM during model load.** The fp16 turbo model is ~1.6 GB; if you're seeing OOM you're likely competing with vLLM. Drop vLLM's `--max-model-len` or `--gpu-memory-utilization`, or stop vLLM during STT bring-up to confirm the NPU service runs in isolation.

**Garbled output / wrong language.** Pass `language=` in the request, or set `WHISPER_DEFAULT_LANGUAGE` in `.env`. Without a hint Whisper auto-detects per request and short clips can mis-route.

## 8. Why turbo, and why a movensys-hosted IR

**Why turbo, not full large-v3.** Full Whisper large-v3 (1.55 B params, 32 decoder layers) is a poor fit for the Panther Lake NPU:

- The NPU's on-die memory is small; it relies on streaming weights from system RAM, which is bandwidth-limited compared to a dGPU. A 1.5 B fp16 model leaves no headroom and stalls on memory.
- The autoregressive decoder runs once per token, so decoder depth dominates wall-clock latency. large-v3-turbo cuts the decoder from 32 → 4 layers with negligible WER regression for English/Korean and ~5–8× faster decoding.

If you specifically need full large-v3 accuracy (e.g. low-resource languages where turbo regresses), point `WHISPER_DEVICE=GPU` or `CPU` and `WHISPER_MODEL_REPO` at a CPU/GPU-targeted IR — the same server code handles both. On NPU, stay on turbo.

**Why a movensys-hosted IR (and not FluidInference's repos).** The community NPU IRs published by FluidInference (last touched July 2025) were exported with an older OpenVINO that emits the legacy two-file decoder shape (`openvino_decoder_model.xml` + `openvino_decoder_with_past_model.xml`) without a `beam_idx` input. OpenVINO 2026's NPU plugin runs a `StatefulToStateless` transform that *requires* `beam_idx`, so loading those older IRs on NPU fails immediately with:

```
RuntimeError: Stateful models without `beam_idx` input are not supported
in StatefulToStateless transformation
```

[`movensys/whisper-large-v3-turbo-fp16-ov-npu`](https://huggingface.co/movensys/whisper-large-v3-turbo-fp16-ov-npu) is a fresh export of `openai/whisper-large-v3-turbo` produced with current `optimum-intel`, which emits the modern single-file stateful decoder with `beam_idx`. fp16 weights, ~1.6 GB, Apache-2.0 licensed (inherits from the base model).

To re-export yourself if needed:

```bash
pip install "optimum-intel[openvino]>=1.20" "transformers>=4.45"
optimum-cli export openvino \
    --model openai/whisper-large-v3-turbo \
    --task automatic-speech-recognition-with-past \
    --weight-format fp16 \
    whisper-large-v3-turbo-fp16-ov-npu
```

## 9. Notes on NPU vs iGPU vs CPU

| | NPU (this service) | iGPU (vLLM-XPU) | CPU |
|---|---|---|---|
| Best for | Whisper-class encoder-decoder, INT4/INT8 transformer inference at low power | LLM/VLM serving, fp16/bf16 throughput | Fallback, debugging, very small models |
| Memory | Shared system RAM, small on-die SRAM | Shared system RAM, larger working set ok | Shared system RAM |
| Quantization | fp16 works; INT4/INT8 reduces memory pressure further when available | fp16/bf16 native; INT4 (AWQ/GPTQ) ok | Anything |
| Power draw | Lowest of the three | Mid | Highest at full load |

For continuous-listening STT on a workstation that's also serving a VLM, the NPU is the right home — it offloads the always-on speech path off the iGPU and leaves the vLLM-XPU service its full memory budget.
