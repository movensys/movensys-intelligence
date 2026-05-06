"""OpenAI-compatible Whisper STT server backed by OpenVINO GenAI on the NPU.

Exposes POST /v1/audio/transcriptions with a multipart `file=` field, matching
the OpenAI audio API closely enough that the standard openai Python client
works against this server when pointed at base_url=http://host:9010/v1.

Why a custom server: as of OpenVINO 2026 the only mature path for Whisper on
the Intel NPU is openvino_genai.WhisperPipeline with STATIC_PIPELINE=True.
There is no off-the-shelf OpenAI-compatible Whisper server that targets the
NPU — speaches/faster-whisper-server use CTranslate2 (CPU/CUDA), not OpenVINO.
This file is intentionally small: load model once, transcribe per request.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import openvino_genai
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from huggingface_hub import snapshot_download

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("whisper-npu")

MODEL_REPO = os.environ.get(
    "WHISPER_MODEL_REPO", "FluidInference/whisper-large-v3-turbo-int4-ov-npu"
)
MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", "/models/whisper-large-v3-turbo-int4-ov-npu")
DEVICE = os.environ.get("WHISPER_DEVICE", "NPU")
DEFAULT_LANGUAGE = os.environ.get("WHISPER_DEFAULT_LANGUAGE", "")
MAX_NEW_TOKENS = int(os.environ.get("WHISPER_MAX_NEW_TOKENS", "448"))
TARGET_SR = 16000


def _resolve_model_path() -> str:
    if Path(MODEL_DIR).exists() and any(Path(MODEL_DIR).iterdir()):
        log.info("using local model at %s", MODEL_DIR)
        return MODEL_DIR
    log.info("downloading %s -> %s", MODEL_REPO, MODEL_DIR)
    return snapshot_download(repo_id=MODEL_REPO, local_dir=MODEL_DIR)


def _load_pipeline() -> openvino_genai.WhisperPipeline:
    model_path = _resolve_model_path()
    log.info("loading WhisperPipeline on %s (this triggers NPU compile, ~30s first run)", DEVICE)
    if DEVICE.upper() == "NPU":
        return openvino_genai.WhisperPipeline(model_path, DEVICE, STATIC_PIPELINE=True)
    return openvino_genai.WhisperPipeline(model_path, DEVICE)


app = FastAPI(title="whisper-npu", version="0.1")
pipe: openvino_genai.WhisperPipeline = _load_pipeline()


def _decode_audio(raw: bytes, filename: str) -> np.ndarray:
    suffix = Path(filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tf:
        tf.write(raw)
        tf.flush()
        audio, _ = librosa.load(tf.name, sr=TARGET_SR, mono=True)
    return audio.astype(np.float32, copy=False)


def _normalize_lang(lang: Optional[str]) -> Optional[str]:
    if not lang:
        return None
    lang = lang.strip()
    if not lang:
        return None
    return lang if lang.startswith("<|") else f"<|{lang}|>"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "device": DEVICE, "model": MODEL_REPO}


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
    del model, temperature  # accepted for OpenAI client compatibility, ignored
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")

    try:
        audio = _decode_audio(raw, file.filename or "audio.wav")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not decode audio: {e}") from e

    config = pipe.get_generation_config()
    config.task = "transcribe"
    config.max_new_tokens = MAX_NEW_TOKENS
    lang_token = _normalize_lang(language) or _normalize_lang(DEFAULT_LANGUAGE)
    if lang_token:
        config.language = lang_token

    try:
        result = pipe.generate(audio, config)
    except Exception as e:
        log.exception("inference failed")
        raise HTTPException(status_code=500, detail=f"inference failed: {e}") from e

    text = str(result).strip()

    if response_format in ("text", "txt"):
        return PlainTextResponse(text)
    return JSONResponse({"text": text})
