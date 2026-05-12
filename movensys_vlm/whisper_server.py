"""OpenAI-compatible Whisper STT server, backend selectable at startup.

Two backends share this server:

- `openvino` (default): OpenVINO GenAI WhisperPipeline, targets the Intel NPU
  on Panther Lake (Core Ultra). Requires the `openvino_genai` runtime in the
  image; see Dockerfile.whisper-npu.
- `transformers`: HuggingFace transformers + PyTorch on CUDA, targets the
  Jetson AGX Thor iGPU (Blackwell, sm_110). We use transformers rather than
  faster-whisper here because the upstream ctranslate2 wheels for arm64 are
  not built with CUDA support, so faster-whisper would silently fall back to
  CPU on Thor. transformers + torch ride on the sm_110-tuned PyTorch shipped
  in the NVIDIA Jetson base image — no source build, no Jetson-wheel-version
  matching. See Dockerfile.whisper-thor.

The HTTP surface is identical across backends: POST /v1/audio/transcriptions
with a multipart `file=` field, response shape `{"text": "..."}` (or plain
text when `response_format=text`). Clients pointed at base_url=http://host:9010/v1
work against either deployment with no code changes — only the base_url moves.

Why one server file: the two backends differ only in (a) how the model is
loaded and (b) the single transcribe call. Splitting the FastAPI plumbing,
audio decoding, and request validation across two files would invite drift.
A small if/else at module scope keeps both paths visible and lets the same
deployment knobs (`HF_WHISPER_REPO`, `WHISPER_MODEL_DIR`,
`WHISPER_DEFAULT_LANGUAGE`) apply uniformly.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Protocol

import librosa
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from huggingface_hub import snapshot_download

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("whisper")

BACKEND = os.environ.get("WHISPER_BACKEND", "openvino").lower()


def _autodetect_ov_device() -> str:
    # NPU > GPU > CPU. We query OpenVINO directly because that's the same list
    # the WhisperPipeline will see at compile time — no point preferring a
    # device the runtime can't actually target.
    try:
        import openvino as ov

        available = {d.split(".")[0].upper() for d in ov.Core().available_devices}
    except Exception as e:
        log.warning("openvino device probe failed (%s); defaulting to CPU", e)
        return "CPU"
    for preferred in ("NPU", "GPU", "CPU"):
        if preferred in available:
            return preferred
    return "CPU"


# Per-device OV-IR model defaults. `movensys/whisper-large-v3-turbo-fp16-ov-npu`
# is a modern stateful export (single-file decoder + `beam_idx` input) that
# OV 2026 will load on NPU, GPU, *and* CPU. We use it for every device rather
# than swapping in legacy FluidInference NPU IRs, which OV 2026's NPU plugin
# rejects via the StatefulToStateless transform. See
# docker/whisper/whisper-npu-README.md for the export-format rationale.
_MOVENSYS_OV_REPO = ("movensys/whisper-large-v3-turbo-fp16-ov-npu",
                     "/models/whisper-large-v3-turbo-fp16-ov-npu")
_OV_MODEL_BY_DEVICE = {
    "NPU": _MOVENSYS_OV_REPO,
    "GPU": _MOVENSYS_OV_REPO,
    "CPU": _MOVENSYS_OV_REPO,
}

if BACKEND == "openvino":
    _requested = os.environ.get("WHISPER_DEVICE", "AUTO").strip().upper() or "AUTO"
    _DEFAULT_DEVICE = _autodetect_ov_device() if _requested == "AUTO" else _requested
    _DEFAULT_REPO, _DEFAULT_DIR = _OV_MODEL_BY_DEVICE.get(
        _DEFAULT_DEVICE, _OV_MODEL_BY_DEVICE["CPU"]
    )
    log.info(
        "openvino backend: device=%s (requested=%s) default_model=%s",
        _DEFAULT_DEVICE, _requested, _DEFAULT_REPO,
    )
elif BACKEND == "transformers":
    _DEFAULT_REPO = "openai/whisper-large-v3"
    _DEFAULT_DIR = "/models/whisper-large-v3"
    _DEFAULT_DEVICE = os.environ.get("WHISPER_DEVICE", "cuda")
else:
    raise RuntimeError(f"unknown WHISPER_BACKEND={BACKEND!r}; expected 'openvino' or 'transformers'")

MODEL_REPO = os.environ.get("HF_WHISPER_REPO", _DEFAULT_REPO)
MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", _DEFAULT_DIR)
DEVICE = _DEFAULT_DEVICE
DEFAULT_LANGUAGE = os.environ.get("WHISPER_DEFAULT_LANGUAGE", "")
MAX_NEW_TOKENS = int(os.environ.get("WHISPER_MAX_NEW_TOKENS", "448"))
TORCH_DTYPE = os.environ.get("WHISPER_TORCH_DTYPE", "float16")  # transformers only
CHUNK_LENGTH_S = int(os.environ.get("WHISPER_CHUNK_LENGTH_S", "30"))  # transformers only
TARGET_SR = 16000


class _Backend(Protocol):
    def transcribe(self, audio: np.ndarray, language: Optional[str], temperature: float) -> str: ...


def _resolve_model_path() -> str:
    if Path(MODEL_DIR).exists() and any(Path(MODEL_DIR).iterdir()):
        log.info("using local model at %s", MODEL_DIR)
        return MODEL_DIR
    log.info("downloading %s -> %s", MODEL_REPO, MODEL_DIR)
    return snapshot_download(repo_id=MODEL_REPO, local_dir=MODEL_DIR)


class _OpenVINOBackend:
    def __init__(self) -> None:
        import openvino_genai

        model_path = _resolve_model_path()
        log.info(
            "loading WhisperPipeline on %s from %s (first-run compile may take ~30s)",
            DEVICE, model_path,
        )
        if DEVICE.upper() == "NPU":
            self._pipe = openvino_genai.WhisperPipeline(model_path, DEVICE, STATIC_PIPELINE=True)
        else:
            self._pipe = openvino_genai.WhisperPipeline(model_path, DEVICE)

    def transcribe(self, audio: np.ndarray, language: Optional[str], temperature: float) -> str:
        del temperature  # OpenVINO GenAI Whisper doesn't expose a sampling temperature knob
        config = self._pipe.get_generation_config()
        config.task = "transcribe"
        config.max_new_tokens = MAX_NEW_TOKENS
        lang_token = _normalize_lang_ov(language) or _normalize_lang_ov(DEFAULT_LANGUAGE)
        if lang_token:
            config.language = lang_token
        return str(self._pipe.generate(audio, config)).strip()


class _TransformersBackend:
    def __init__(self) -> None:
        import torch
        from transformers import pipeline

        # transformers resolves HF repos itself, but we still prefer a pre-populated
        # local dir when available so we don't pay a download on container start.
        model_id = MODEL_DIR if (Path(MODEL_DIR).exists() and any(Path(MODEL_DIR).iterdir())) else MODEL_REPO
        dtype = {
            "float16": torch.float16,
            "fp16": torch.float16,
            "bfloat16": torch.bfloat16,
            "bf16": torch.bfloat16,
            "float32": torch.float32,
            "fp32": torch.float32,
        }.get(TORCH_DTYPE.lower())
        if dtype is None:
            raise RuntimeError(f"unknown WHISPER_TORCH_DTYPE={TORCH_DTYPE!r}")

        log.info(
            "loading transformers ASR pipeline(%s) on device=%s dtype=%s",
            model_id, DEVICE, TORCH_DTYPE,
        )
        # NB: do NOT set chunk_length_s on the pipeline at construction time.
        # Doing so silently turns on the timestamp-decoding path for *every*
        # call, which on short clips (<30s) drops the model into a dash/dot
        # repetition loop because `return_timestamps=True` is then required
        # but the timestamp logits processor doesn't always get attached on
        # transformers 4.45+. Instead we pass chunk_length_s per call below,
        # only when the audio is actually long enough to need chunking.
        self._pipe = pipeline(
            task="automatic-speech-recognition",
            model=model_id,
            torch_dtype=dtype,
            device=DEVICE,
        )

    def transcribe(self, audio: np.ndarray, language: Optional[str], temperature: float) -> str:
        lang = (language or "").strip() or (DEFAULT_LANGUAGE or "").strip() or None
        # transformers passes language/task through generate_kwargs to Whisper's
        # forced decoder ids. temperature=0 is the deterministic-greedy default
        # that the OpenAI client sends; we only pass it through when nonzero so
        # we don't accidentally enable sampling on a 0.0 request.
        generate_kwargs: dict = {"task": "transcribe"}
        if lang:
            generate_kwargs["language"] = lang
        if temperature and temperature > 0:
            generate_kwargs["do_sample"] = True
            generate_kwargs["temperature"] = float(temperature)

        call_kwargs: dict = {"generate_kwargs": generate_kwargs}
        # Whisper's native window is 30s. For longer audio we hand the pipeline
        # a chunk length and ask for timestamps, which is the only way the HF
        # pipeline knows how to stitch chunks back together. Short clips skip
        # both — that path goes through plain greedy decoding and is robust.
        duration_s = len(audio) / TARGET_SR
        if duration_s > 30.0:
            call_kwargs["chunk_length_s"] = CHUNK_LENGTH_S
            call_kwargs["return_timestamps"] = True

        result = self._pipe({"array": audio, "sampling_rate": TARGET_SR}, **call_kwargs)
        return str(result["text"]).strip()


def _normalize_lang_ov(lang: Optional[str]) -> Optional[str]:
    """OpenVINO GenAI wants the Whisper language token form, e.g. '<|en|>'."""
    if not lang:
        return None
    lang = lang.strip()
    if not lang:
        return None
    return lang if lang.startswith("<|") else f"<|{lang}|>"


def _load_backend() -> _Backend:
    if BACKEND == "openvino":
        return _OpenVINOBackend()
    return _TransformersBackend()


app = FastAPI(title=f"whisper-{BACKEND}", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
backend: _Backend = _load_backend()


def _decode_audio(raw: bytes, filename: str) -> np.ndarray:
    suffix = Path(filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tf:
        tf.write(raw)
        tf.flush()
        audio, _ = librosa.load(tf.name, sr=TARGET_SR, mono=True)
    return audio.astype(np.float32, copy=False)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "backend": BACKEND, "device": DEVICE, "model": MODEL_REPO}


@app.get("/v1/models")
def list_models() -> dict:
    return {
        "object": "list",
        "data": [{"id": MODEL_REPO, "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(default=MODEL_REPO),
    language: Optional[str] = Form(default=None),
    response_format: str = Form(default="json"),
    temperature: float = Form(default=0.0),
):
    del model  # accepted for OpenAI client compatibility, ignored
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")

    try:
        audio = _decode_audio(raw, file.filename or "audio.wav")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not decode audio: {e}") from e

    try:
        text = backend.transcribe(audio, language, temperature)
    except Exception as e:
        log.exception("inference failed")
        raise HTTPException(status_code=500, detail=f"inference failed: {e}") from e

    if response_format in ("text", "txt"):
        return PlainTextResponse(text)
    return JSONResponse({"text": text})
