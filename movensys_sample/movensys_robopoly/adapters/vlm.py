"""VLM intent adapter — routed through movensys_vlm_container.

The orchestrator's /api/vlm/infer returns free-form text from the VLM, so
this adapter builds a strict-JSON system prompt to coerce a structured
{intent, args, confidence} response, then parses it.

Intent vocabulary is owned by this package; non-vocabulary intents are
collapsed to `unknown`.

Image grounding: the orchestrator pulls images directly from the ROS
camera identified by `camera` ("top" | "hand" | "none"). The legacy
`image_b64` parameter is accepted but ignored — there is no path to ship
raw bytes through the orchestrator's API today.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx


log = logging.getLogger(__name__)

Mode = Literal["live", "stub"]
Camera = Literal["top", "hand", "none"]

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


_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _strip_code_fence(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def _build_system_prompt() -> str:
    vocab = ", ".join(sorted(INTENT_VOCABULARY))
    return (
        "You are an intent classifier for a Monopoly-style board game.\n"
        "Read the user utterance (and any board context provided) and reply "
        "with STRICT JSON in this shape:\n"
        '  {"intent": "<one of: ' + vocab + '>", '
        '"args": {<intent-specific args, may be empty>}, '
        '"confidence": <number between 0 and 1>}\n'
        "Return ONLY the JSON object. No prose, no markdown fences, no commentary."
    )


@dataclass
class VLMAdapter:
    base_url: str
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "VLMAdapter":
        return cls(base_url=os.environ.get("MOVENSYS_VLM_URL", "").strip())

    @property
    def mode(self) -> Mode:
        return "live" if self.base_url else "stub"

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode, "endpoint": "/api/vlm/infer"}
        if self.base_url:
            payload["url"] = self.base_url
        return payload

    async def infer(
        self,
        *,
        text: str | None = None,
        image_b64: str | None = None,
        context: dict[str, Any] | None = None,
        camera: Camera = "none",
    ) -> dict[str, Any]:
        """POST /api/vlm/infer -> {intent, args, confidence?}. Stub raises."""
        if self.mode == "stub":
            raise RuntimeError("LLM adapter is in stub mode; use /api/debug/simulate_llm_intent")

        if image_b64 is not None:
            # The orchestrator pulls camera frames itself; raw bytes have no
            # transport. Pass camera="top" or "hand" to ground on a live frame.
            log.debug("VLMAdapter: image_b64 ignored — use camera='top'|'hand' instead")

        prompt_parts: list[str] = []
        if text:
            prompt_parts.append(text)
        if context:
            prompt_parts.append(f"Context: {json.dumps(context, ensure_ascii=False)}")
        user_prompt = "\n\n".join(prompt_parts) or "Classify the player's intent."

        body = {
            "camera": camera,
            "prompt": user_prompt,
            "system_prompt": _build_system_prompt(),
            "max_tokens": 256,
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.base_url}/api/vlm/infer", json=body)
            r.raise_for_status()
            data = r.json()

        if data.get("error"):
            log.warning("VLMAdapter: orchestrator returned error: %s", data["error"])
            return {"intent": "unknown", "args": {}, "confidence": None}

        raw = _strip_code_fence(str(data.get("response") or ""))
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("VLMAdapter: response not valid JSON: %r", raw[:200])
            return {"intent": "unknown", "args": {}, "confidence": None}

        intent = obj.get("intent", "unknown")
        if intent not in INTENT_VOCABULARY:
            intent = "unknown"
        return {
            "intent": intent,
            "args": obj.get("args") or {},
            "confidence": obj.get("confidence"),
        }
