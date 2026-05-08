"""Dice & horse pick-and-place adapter (PRD §8.3).

Stub when ROBOT_SERVICE_URL is empty: dice rolls fall back to RNG,
horse-move requests become no-ops, /api/robot/health reports mode=stub.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Any, Literal

import httpx


Mode = Literal["live", "stub"]


@dataclass
class RobotAdapter:
    url: str
    timeout_s: float = 5.0

    @classmethod
    def from_env(cls) -> "RobotAdapter":
        return cls(url=os.environ.get("ROBOT_SERVICE_URL", "").strip())

    @property
    def mode(self) -> Mode:
        return "live" if self.url else "stub"

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        if self.url:
            payload["url"] = self.url
        return payload

    async def roll_dice(self) -> int:
        """Return 1..6. Stub mode uses local RNG."""
        if self.mode == "stub":
            return random.randint(1, 6)
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.url}/dice/roll")
            r.raise_for_status()
            return int(r.json()["value"])

    async def move_piece(self, player: str, from_tile: int, to_tile: int) -> bool:
        """Fire-and-forget per PRD §8.3. Returns whether the call was accepted."""
        if self.mode == "stub":
            return True
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                f"{self.url}/horse/move",
                json={"player": player, "from_tile": from_tile, "to_tile": to_tile},
            )
            r.raise_for_status()
            return bool(r.json().get("accepted", True))

    async def base_position(self) -> bool:
        if self.mode == "stub":
            return True
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.url}/base_position")
            r.raise_for_status()
            return bool(r.json().get("accepted", True))
