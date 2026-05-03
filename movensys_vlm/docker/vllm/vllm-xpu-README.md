# Running vLLM on Intel XPU (Panther Lake iGPU)

Tested target:
- Intel Core Ultra (Panther Lake) with Xe3 integrated GPU
- Ubuntu 24.04
- Intel GPU compute runtime + Level Zero loader
- vLLM built from source via the upstream [`docker/Dockerfile.xpu`](https://github.com/vllm-project/vllm/blob/main/docker/Dockerfile.xpu)

Unlike the Thor setup (which layers on top of NVIDIA's pre-built vLLM container), there is no pre-built XPU image published by vLLM. We build from source using their multi-stage Dockerfile, which pulls Intel oneAPI 2025.3, the Intel Graphics Compiler, the compute runtime, and Python 3.12 — then compiles vLLM with `VLLM_TARGET_DEVICE=xpu`.

## 1. Prerequisites

### Intel GPU drivers on the host

Panther Lake needs a recent Intel compute stack. Follow the [Intel GPU driver install guide](https://dgpu-docs.intel.com/driver/installation.html) for your kernel/distro. Verify the device shows up:

```bash
ls -l /dev/dri              # should list cardN and renderDN
clinfo | grep -i 'Device Name'   # should report an Intel GPU
```

Add your user to the `render` and `video` groups so the container (and host tools) can access `/dev/dri`:

```bash
sudo usermod -aG render,video $USER
newgrp render
```

### Disk space

The XPU image is ~15–20 GB built. Reserve ~50 GB free under `~/` for the image, vLLM source checkout, and a model.

### vLLM source checkout

The build context is the vLLM repo itself — its `Dockerfile.xpu` copies source into the image. Clone it next to this repo (or anywhere; just point `VLLM_SRC` at it):

```bash
# Default location used by vllm-xpu-compose.yml
git clone https://github.com/vllm-project/vllm.git ~/git/vllm
cd ~/git/vllm
git checkout v0.20.0     # pin to a release; main is a development branch
```

The compose file's default `context` is `../../../../vllm` relative to `movensys_vlm/docker/vllm/`, which resolves to a sibling of `movensys-intelligence/`. Override with the `VLLM_SRC` env var if your checkout lives elsewhere.

## 2. Build the image

```bash
cd movensys_vlm/docker/vllm

# Default: expects vLLM source at ../../../../vllm
docker compose -f vllm-xpu-compose.yml build

# Or point at a different checkout:
VLLM_SRC=/path/to/vllm docker compose -f vllm-xpu-compose.yml build
```

The first build is slow (oneAPI install + vLLM compile, often 30+ minutes) and needs `--shm-size=4g` (the compose file sets this via `shm_size`).

## 3. Download a model

Same flow as the Thor README — gated models need a Hugging Face token and license acceptance:

```bash
mkdir -p ~/models
pip install -U "huggingface_hub[cli]"
hf auth login

hf download google/gemma-4-E4B-it --local-dir ~/models/gemma-4-E4B-it
```

## 4. Run as a service

```bash
cd movensys_vlm/docker/vllm

docker compose -f vllm-xpu-compose.yml up -d
docker compose -f vllm-xpu-compose.yml logs -f
docker compose -f vllm-xpu-compose.yml ps
docker compose -f vllm-xpu-compose.yml down
```

The container runs `--privileged` with `/dev/dri` mounted and `ipc=host` — these are required by the upstream XPU Dockerfile for Level Zero / oneCCL to talk to the GPU.

### Important flags for Panther Lake

| Flag | Why |
|---|---|
| `--dtype=float16` | XPU path supports fp16/bf16; the iGPU has no fp8 fast-path. Use `bfloat16` if the model prefers it. |
| `--max-model-len=8192` | KV cache lives in shared system memory on iGPU — keep it small. Lower if you OOM. |
| `--enforce-eager` *(optional)* | Skips graph capture. Helpful if compilation hangs or OOMs on first warmup. |

Tensor/pipeline parallel only makes sense with multiple discrete GPUs; on a single iGPU, leave them at the default of 1.

## 5. Test the endpoint

```bash
curl http://localhost:8000/v1/models

curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-e4b",
    "messages": [{"role":"user","content":"Hello, who are you?"}]
  }'
```

## 6. Troubleshooting

**`Failed to load Level Zero` / no XPU detected.** Host driver isn't loaded or your user can't access `/dev/dri`. Check `clinfo` on the host first — if it doesn't see the GPU there, the container won't either. Confirm the `render` group ownership of `/dev/dri/renderD*` matches a group your user is in.

**Build fails resolving `intel/deep-learning-essentials:2025.3.2-0-devel-ubuntu24.04`.** Network or registry issue — the base image pulls from Docker Hub. Retry, or pre-pull: `docker pull intel/deep-learning-essentials:2025.3.2-0-devel-ubuntu24.04`.

**OOM during model load.** Panther Lake iGPU shares system RAM. Drop `--max-model-len`, pick a smaller model (e.g. `google/gemma-2-2b-it`), or quantize. Don't run a 9B+ BF16 model on an iGPU without checking memory headroom first.

**Slow first request.** Triton kernels are JIT-compiled on first use; warm-up can take a minute. Subsequent requests use the cache.

**Want to pin a different vLLM version.** `cd` into your vLLM checkout, `git checkout <tag>`, then rebuild. The image tag in the compose file (`vllm-xpu:source`) doesn't encode the version — bump it manually if you want to keep multiple builds around.

## 7. Notes on iGPU vs discrete Arc

The upstream XPU path is primarily tuned for Intel Data Center GPUs and discrete Arc. Panther Lake's Xe3 iGPU uses the same Level Zero / SYCL stack so it loads, but expect:

- Lower throughput than Arc due to limited memory bandwidth and EU count.
- Memory pressure: KV cache, activations, and model weights all share system RAM with the OS. Budget accordingly.
- Some kernels may not be tuned for Xe3 yet and fall back to slower paths.

For serious inference workloads on this class of hardware, prefer 2B–4B models in fp16/bf16, or 7B+ models in INT4 (AWQ/GPTQ) once you've confirmed the kernels work on your stack.
