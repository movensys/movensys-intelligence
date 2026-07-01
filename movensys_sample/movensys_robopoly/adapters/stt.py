"""Whisper STT adapter — routed through movensys_vlm_container.

All robopoly external comms go through the orchestrator's HTTP API. This
adapter posts audio to `POST {MOVENSYS_VLM_URL}/api/whisper/transcribe`.

Stub when MOVENSYS_VLM_URL is empty: UI falls back to text input and
/api/debug/inject_utterance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx


Mode = Literal["live", "stub"]


@dataclass
class STTAdapter:
    base_url: str
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "STTAdapter":
        return cls(base_url=os.environ.get("MOVENSYS_VLM_URL", "").strip())

    @property
    def mode(self) -> Mode:
        return "live" if self.base_url else "stub"

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode, "endpoint": "/api/whisper/transcribe"}
        if self.base_url:
            payload["url"] = self.base_url
        return payload

    async def transcribe(self, audio: bytes, filename: str = "utterance.wav") -> str:
        """POST audio -> {text}. Stub mode raises (caller should route to debug input)."""
        if self.mode == "stub":
            raise RuntimeError("STT adapter is in stub mode; use /api/debug/inject_utterance")
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            # The orchestrator expects the multipart field to be named `file`.
            files = {"file": (filename, audio, "audio/wav")}
            r = await client.post(f"{self.base_url}/api/whisper/transcribe", files=files)
            r.raise_for_status()
            data = r.json()
        if data.get("error"):
            raise RuntimeError(f"whisper error: {data['error']}")
        return str(data.get("text") or "")
