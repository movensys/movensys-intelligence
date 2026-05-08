"""Whisper STT adapter (PRD §8.1).

Stub when STT_SERVICE_URL is empty: UI falls back to text input and
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
    url: str
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "STTAdapter":
        return cls(url=os.environ.get("STT_SERVICE_URL", "").strip())

    @property
    def mode(self) -> Mode:
        return "live" if self.url else "stub"

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        if self.url:
            payload["url"] = self.url
        return payload

    async def transcribe(self, audio: bytes, filename: str = "utterance.wav") -> str:
        """POST audio -> {text}. Stub mode raises (caller should route to debug input)."""
        if self.mode == "stub":
            raise RuntimeError("STT adapter is in stub mode; use /api/debug/inject_utterance")
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            files = {"audio": (filename, audio, "application/octet-stream")}
            r = await client.post(f"{self.url}/stt", files=files)
            r.raise_for_status()
            return str(r.json()["text"])
