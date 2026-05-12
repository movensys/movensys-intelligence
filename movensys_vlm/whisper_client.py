import os
from typing import Optional

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        base_url = os.environ.get("WHISPER_BASE_URL", "http://localhost:9010/v1")
        api_key = os.environ.get("HF_TOKEN") or "EMPTY"
        timeout = float(os.environ.get("WHISPER_TIMEOUT") or 60)
        _client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    return _client


async def transcribe(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    content_type: str = "audio/wav",
    language: Optional[str] = None,
    response_format: str = "json",
) -> str:
    client = get_client()
    model = os.environ.get("WHISPER_MODEL_REPO") or "whisper"
    kwargs: dict = {
        "file": (filename, audio_bytes, content_type),
        "model": model,
        "response_format": response_format,
    }
    if language:
        kwargs["language"] = language
    result = await client.audio.transcriptions.create(**kwargs)
    return result.text if hasattr(result, "text") else str(result)
