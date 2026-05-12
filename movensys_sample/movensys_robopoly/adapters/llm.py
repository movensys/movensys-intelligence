"""Gemma 4 LLM adapter (PRD §8.2).

Intent vocabulary is owned by this package; the request schema is fixed
here so the Gemma team implements to our contract.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx


Mode = Literal["live", "stub"]

INTENT_VOCABULARY = frozenset(
    {
        "start_game",
        "roll_dice",
        "end_turn",
        "buy",
        "buy_and_build",
        "skip",
        "jail_exit",
        "mortgage",
        "unmortgage",
        "sell_building",
        "board_query",
        "unknown",
    }
)


@dataclass
class LLMAdapter:
    url: str
    timeout_s: float = 15.0

    @classmethod
    def from_env(cls) -> "LLMAdapter":
        return cls(url=os.environ.get("LLM_SERVICE_URL", "").strip())

    @property
    def mode(self) -> Mode:
        return "live" if self.url else "stub"

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        if self.url:
            payload["url"] = self.url
        return payload

    async def infer(
        self,
        *,
        text: str | None = None,
        image_b64: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /infer -> {intent, args, confidence?}. Stub raises."""
        if self.mode == "stub":
            raise RuntimeError("LLM adapter is in stub mode; use /api/debug/simulate_llm_intent")
        payload = {"text": text, "image_b64": image_b64, "context": context or {}}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.url}/infer", json=payload)
            r.raise_for_status()
            data = r.json()
        intent = data.get("intent", "unknown")
        if intent not in INTENT_VOCABULARY:
            intent = "unknown"
        return {"intent": intent, "args": data.get("args") or {}, "confidence": data.get("confidence")}
