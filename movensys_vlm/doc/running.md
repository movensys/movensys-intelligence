# Running Movensys-Manipulator
check `doc/` number 1, 2, and 6

# Bashrc Setup
```
export XPU_CORE=nvidia-gpu              #support{nvidia-gpu, intel-xpu} 
```
```
source ~/.bashrc
```



# Step 1: Stop and delete existed docker
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
```
## Step 2: For Nvidia Desktop, Jetson Thor, Intel B60
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml down
```
## Step 3: Release memory stuck for Jetson Thor and Intel Panther lake
```
sync && sudo sysctl vm.drop_caches=3
```




# Setup Docker 
## Step 4a: VLLM For Nvidia Desktop, Jetson Thor, Intel B60 
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml up -d
```
## Step 4b: VLLM For Intel Panther Lake [Docker setup is failed]
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
./vllm-intel-build.sh
./vllm-intel-run.sh
```
Wait until `application startup complete` in docker logs or terminal






## Step 5: setup Movensys_vlm and vector DB
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml build
COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml up -d
```

### Option 5a. w/o phoenix
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml up -d
```


### Option 5b. w phoenix
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
docker run -d --rm --name phoenix \
    -p 6006:6006 -p 4317:4317 \
    arizephoenix/phoenix:latest
```
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
export PHOENIX_TRACING=1
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml up -d
```





## Step 6: Whispher english mode
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
WHISPER_DEFAULT_LANGUAGE=en COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml build
WHISPER_DEFAULT_LANGUAGE=en COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml up -d
```


# Running
open `localhost:8000` for robot controller
open `localhost:8000/vlm` for VLM
open `localhost:8000/docs` for checking APIs
















---

# Backend services (vLLM + Whisper)

The manipulator API talks to two backend services over HTTP:

- **vLLM** — VLM/LLM serving on port `9000` (`VLM_BASE_URL` in `.env`).
- **Whisper** — STT on port `9010`.

Each has its own compose file and its own detailed README. Pick the pair that matches your hardware:

| Hardware | vLLM | Whisper |
|---|---|---|
| Jetson AGX Thor (Blackwell iGPU) | [docker/vllm/vllm-thor-README.md](../docker/vllm/vllm-thor-README.md) | [docker/whisper/whisper-thor-README.md](../docker/whisper/whisper-thor-README.md) |
| Intel Core Ultra (Panther Lake, NPU + iGPU) | see [Panther Lake (XPU) — current approach](#panther-lake-xpu--current-approach) | [docker/whisper/whisper-npu-README.md](../docker/whisper/whisper-npu-README.md) |

Both services on the same host coexist on different ports; bring them up in either order.

## docker/vllm — Thor

```bash
cd movensys_vlm/docker/vllm
docker compose -f vllm-thor-compose.yml build
docker compose -f vllm-thor-compose.yml up -d
docker compose -f vllm-thor-compose.yml logs -f
```

Serves Gemma 4 (`google/gemma-4-E4B-it` by default) on `http://localhost:9000/v1`. Requires Thor on MAXN (`sudo nvpmodel -m 0 && sudo jetson_clocks`). Full setup, model download, and tuning flags in [vllm-thor-README.md](../docker/vllm/vllm-thor-README.md).

## docker/whisper — Thor (iGPU) or Panther Lake (NPU)

Two separate compose files share `server.py` but target different backends:

```bash
cd movensys_vlm/docker/whisper

# Jetson Thor — HF transformers on CUDA iGPU, full whisper-large-v3 fp16
docker compose -f whisper-thor-compose.yml up -d

# Panther Lake — OpenVINO GenAI on the NPU, whisper-large-v3-turbo fp16 IR
docker compose -f whisper-npu-compose.yml up -d
```

Both expose the OpenAI-compatible `POST /v1/audio/transcriptions` on port `9010`. Test:

```bash
curl http://localhost:9010/health
curl -X POST http://localhost:9010/v1/audio/transcriptions \
  -F "file=@sample.wav" -F "language=en" -F "response_format=json"
```

The NPU path uses the `movensys/whisper-large-v3-turbo-fp16-ov-npu` IR (re-exported for OpenVINO 2026 with the modern stateful `beam_idx` decoder shape) — see [whisper-npu-README.md](../docker/whisper/whisper-npu-README.md) for why the older community IRs don't load on OV 2026's NPU plugin.

Cold-start NPU compile is ~9 minutes; compiled blobs are cached under `~/.cache/ze_intel_npu_cache` so subsequent restarts are near-instant.

---

# Panther Lake (XPU) — current approach

**Status: Docker is on hold for vLLM on Panther Lake's iGPU.**

The upstream vLLM XPU container path runs into a `torch-xpu-ops` vectorized-gather kernel assertion (`index out of bounds`) when serving Gemma 4 on the Xe3 iGPU, plus driver fragility from the PREEMPT_RT host kernel interacting with the Intel `xe` driver and Level Zero.

For now we **build vLLM from source on the host** instead, following the upstream [build-wheel-from-source guide](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/#build-wheel-from-source):

```bash
# Python 3.12 venv (mandatory — vllm-xpu-kernels wheel is 3.12-only)
uv venv --python 3.12 --seed --managed-python ~/.venvs/vllm-xpu
source ~/.venvs/vllm-xpu/bin/activate

git clone https://github.com/vllm-project/vllm.git ~/git/vllm
cd ~/git/vllm && git checkout v0.20.0

pip install -v -r requirements/xpu.txt
pip uninstall -y triton triton-xpu
pip install triton-xpu==3.6.0 --extra-index-url https://download.pytorch.org/whl/xpu
VLLM_TARGET_DEVICE=xpu pip install --no-build-isolation -e . -v
```

Run:

```bash
source ~/.venvs/vllm-xpu/bin/activate
vllm serve ~/models/gemma-4-E4B-it \
  --served-model-name=gemma-4-E4B-it-ptl \
  --port=9000 \
  --max-model-len=2048 \
  --gpu-memory-utilization=0.7 \
  --attention-backend TRITON_ATTN \
  --enforce-eager \
  --limit-mm-per-prompt='{"image": 1, "video": 0}'
```

`--limit-mm-per-prompt='{"video": 0}'` is required — Gemma 4's video encoder hits a long silent profile-run inside `_avg_pool_by_positions` on Xe3 otherwise.

The Docker assets ([Dockerfile.xpu](../docker/vllm/) and [vllm-xpu-compose.yml](../docker/vllm/vllm-xpu-compose.yml)) are kept in-tree as documentation of what we tried. Revisit them once any of: (a) a vLLM/torch-xpu-ops release with a fix lands, (b) the host moves off PREEMPT_RT, or (c) a non-multimodal model works fully in-container. Full context in [vllm-xpu-README.md](../docker/vllm/vllm-xpu-README.md).

The Whisper service on this same machine is unaffected — it runs on the **NPU** (`/dev/accel/accel0`), not the iGPU, and the NPU container path works today.

---

# Tracing with Phoenix (troubleshooting)

[Arize Phoenix](https://phoenix.arize.com) is wired into the orchestrator
as an opt-in tool for diagnosing VLM / Whisper inference latency and
connection failures. The orchestrator auto-instruments the OpenAI
client and **exports spans to a standalone Phoenix server** — every
`chat.completions.create` and `audio.transcriptions.create` call
produces a span with model, token counts, image payload size, and
wall-clock latency.

Tracing is **off by default** — production / demo runs pay zero cost.

### Enable

Step 1 — run Phoenix in its own container (do this once; leave it up):

```bash
docker run -d --rm --name phoenix \
    -p 6006:6006 -p 4317:4317 \
    arizephoenix/phoenix:latest
```

Step 2 — flip the orchestrator flag and recreate it so it picks up the env:

```bash
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
export PHOENIX_TRACING=1
# Optional; defaults to http://localhost:6006, which works as-is when
# Phoenix is on the same host (orchestrator runs network_mode: host).
# export PHOENIX_COLLECTOR_ENDPOINT=http://<phoenix-host>:6006
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml \
    up -d --force-recreate
```

`--build` is not required — the Phoenix exporter packages
(`arize-phoenix`, `openinference-instrumentation-openai`) are baked into
the image; only the env var toggles activation.

### Open the UI

```
http://<phoenix-host>:6006
```

Drive a VLM or Whisper call (roll dice, click Ask VLM, press Rec) and
the trace appears in the **Traces** tab under the `movensys-vlm`
project. Each row shows total wall time; clicking expands the waterfall
with sub-spans for image upload, request, and response parsing.

### What's traced and what isn't

| Traced | Not traced |
|---|---|
| `vlm_client.infer` → `client.chat.completions.create` | GPU-side inference cost inside vLLM / Whisper server |
| `whisper_client.transcribe` → `client.audio.transcriptions.create` | ROS topic latency for `latest_top_rgb_image` |
| Model name, token counts, image base64 size | Browser-side `captureBoardImage` time |
| Per-call latency end-to-end (orchestrator-side) | Memory-client (Qdrant) calls |

For GPU inference time, check the vLLM / Whisper server logs separately
(`docker logs <vllm-container>` etc.) — Phoenix sees only the HTTP
client's view.

### Disable

```bash
unset PHOENIX_TRACING
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml \
    up -d --force-recreate
```

Env vars are read at process start; a plain `docker restart` is not
enough — the container must be recreated to pick up the new value.
