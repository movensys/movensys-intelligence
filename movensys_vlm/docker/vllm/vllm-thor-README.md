## 2. Build the image

The base NVIDIA container ships vLLM 0.19.0 + transformers 4.57.6, which doesn't recognize the `gemma4` model_type. We layer vLLM 0.20.0 + a newer transformers on top via [Dockerfile.vllm-thor](Dockerfile.vllm-thor).

The compose file's `build:` block points at this Dockerfile, so `docker compose up -d` (see §4) will build the image on first run. To build it explicitly:

```bash
cd movensys_vlm/docker/vllm
docker compose -f vllm-thor-compose.yml build
# or, without compose:
docker build -t vllm-thor:0.20 -f Dockerfile.vllm-thor .
```

### Why `FLASHINFER_DISABLE_VERSION_CHECK=1`

vLLM 0.20.0 wants `flashinfer 0.6.8`, but the NVIDIA container ships a pre-built `flashinfer-jit-cache 0.6.7.post3+nv26.04` compiled for sm_110 (Thor's Blackwell-gen iGPU). Replacing it would lose the Thor-tuned kernels. The env var (set in the compose file) skips the version match check; the on-disk cubins still load fine.

## 3. Download a model

```bash
mkdir -p ~/models
pip install -U "huggingface_hub[cli]"
hf auth login    # paste token from https://huggingface.co/settings/tokens

# Accept the model license on the HF model page first, then:
hf download google/gemma-4-E4B-it --local-dir ~/models/gemma-4-E4B-it
```

Gemma models are gated — accepting the license on Hugging Face with the same account whose token you use is required.

## 4. Run as a service (Docker Compose)

The compose file [vllm-thor-compose.yml](vllm-thor-compose.yml) sets `restart: unless-stopped` so the service comes back after reboots and crashes (but stays down when you stop it manually).

```bash
cd movensys_vlm/docker/vllm

# Start in the background
docker compose -f vllm-thor-compose.yml up -d

# Follow logs
docker compose -f vllm-thor-compose.yml logs -f

# Status
docker compose -f vllm-thor-compose.yml ps

# Restart (e.g. after editing the compose file)
docker compose -f vllm-thor-compose.yml restart

# Stop without removing the container
docker compose -f vllm-thor-compose.yml stop

# Stop and remove the container (volumes are preserved — they're bind mounts)
docker compose -f vllm-thor-compose.yml down
```

To change the model or flags, edit the `command:` block in the compose file and run `restart` (or `up -d` to recreate if you changed `image`/`volumes`/`ports`).

### Important flags for Thor

| Flag | Why |
|---|---|
| `--gpu-memory-utilization=0.3` | Thor uses unified memory shared with the OS. The default 0.9 will OOM the system. Start at 0.3, raise carefully. |
| `--max-model-len=8192` | Caps KV cache size. Lower this if you OOM. |
| `--served-model-name=<name>` | The string clients pass as `"model"` in OpenAI API calls. Decouples the API from the on-disk path. |
| `--enforce-eager` *(optional)* | Disables CUDA graph capture. Adds latency but avoids a memory spike during warmup. Use if loading reboots the box. |

## 5. Test the endpoint

From another terminal on Thor (or any machine on the network):

```bash
curl http://localhost:9000/v1/models

curl http://localhost:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-e4b",
    "messages": [{"role":"user","content":"Hello, who are you?"}]
  }'
```

## 6. Troubleshooting

**System reboots during model load.** Almost always power or memory, not vLLM. Check:
1. `sudo nvpmodel -q` shows MAXN.
2. Lower `--gpu-memory-utilization` (0.3 → 0.2).
3. Add `--enforce-eager`.
4. Try a smaller model first (`google/gemma-2-2b-it`) to confirm the stack works.
5. `sudo dmesg -T | grep -iE 'nvrm|fail|error'` after the next boot — if you see `nvAssertFailed` storms or I2C-to-PMIC timeouts, the driver/firmware install is bad and the unit needs reflashing with a clean JetPack release via SDK Manager.

**`model type 'gemma4' not recognized`.** transformers in the container is too old. Rebuild the image — the Dockerfile pins transformers 5.6+.

**`flashinfer-jit-cache version does not match flashinfer version`.** `FLASHINFER_DISABLE_VERSION_CHECK=1` is missing. Confirm it's in the compose file's `environment:` block.

**Gated model 403 on download.** Accept the license on the model's HF page with the same account as your token.

## 7. Notes on quantized variants

- **NVFP4** is the right format for Thor (Blackwell-gen FP4 tensor cores). Use the same flags but expect to lower `--gpu-memory-utilization` further for larger sizes (e.g. 31B NVFP4 needs careful tuning on 128 GB unified memory).
- **FP8** also works on Blackwell.
- **GPTQ-Marlin** kernels may not have sm_110 builds and can fall back to slow paths or fail.
- **bitsandbytes / GGUF** — avoid for now; new-arch support lags.

When stepping up to larger models, validate the pipeline first with a 2B or 9B BF16 checkpoint before loading 31B+ quantized variants.
