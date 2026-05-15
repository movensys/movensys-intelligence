# Running Movensys-Manipulator
check `doc/` number 1, 2, and 6

# Bashrc Setup
```
export XPU_CORE=nvidia-gpu              #support{nvidia-gpu, intel-xpu} 
```
```
source ~/.bashrc
```




# Setup movensys_vlm
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml up -d
```




# Setup Vector Db
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
docker compose -f vectordb.yaml down
docker compose -f vectordb.yaml build
docker compose -f vectordb.yaml up -d
```




# Setup Vllm 
## For Nvidia Desktop, Jetson Thor, Intel B60 
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml up -d  
```
## For Intel Panther Lake [Docker setup is failed]
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
./vllm-intel-build.sh
./vllm-intel-run.sh
```
## If memory stuck in Intel Panther Lake and Jetson Thor
```
sync && sudo sysctl vm.drop_caches=3
```




# Setup Whisper
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml up -d  
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
