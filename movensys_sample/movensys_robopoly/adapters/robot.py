"""Robot motion adapter — routed through movensys_vlm_container.

All robot motion goes through the orchestrator's HTTP API. The previous
`roll_dice` / `move_piece` / `base_position` methods modeled domain
concepts (Monopoly dice, horse moves) that the orchestrator doesn't
expose — those flows are implemented directly in robopoly's own
`/api/dice/roll_robot` and `/api/move/apply_robot` routes via the
`pick_and_place.py` subprocess, NOT through this adapter.

This adapter now wraps the low-level motion / IO routes the orchestrator
actually offers:
  - POST /api/services/gripper          (open/close)
  - GET  /api/services/get_eef_pose
  - POST /api/move/absolute_cartesian_base
  - POST /api/move/relative_cartesian_base

Stub when MOVENSYS_VLM_URL is empty: methods return success without
performing any motion.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Sequence

import httpx


Mode = Literal["live", "stub"]


def _as_xyz(seq: Sequence[float], name: str) -> list[float]:
    values = list(seq)
    if len(values) != 3:
        raise ValueError(f"{name} must have 3 elements, got {len(values)}")
    return [float(v) for v in values]


@dataclass
class RobotAdapter:
    base_url: str
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "RobotAdapter":
        return cls(base_url=os.environ.get("MOVENSYS_VLM_URL", "").strip())

    @property
    def mode(self) -> Mode:
        return "live" if self.base_url else "stub"

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode, "endpoint": "/api/move/*"}
        if self.base_url:
            payload["url"] = self.base_url
        return payload

    async def gripper(self, open_: bool) -> dict[str, Any]:
        """POST /api/services/gripper {data: bool}."""
        if self.mode == "stub":
            return {"success": True, "message": "stub"}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                f"{self.base_url}/api/services/gripper", json={"data": open_}
            )
            r.raise_for_status()
            return r.json()

    async def get_eef_pose(self) -> dict[str, Any]:
        """GET /api/services/get_eef_pose."""
        if self.mode == "stub":
            return {"success": True, "pos": [0.0, 0.0, 0.0], "rpy": [0.0, 0.0, 0.0], "message": "stub"}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.get(f"{self.base_url}/api/services/get_eef_pose")
            r.raise_for_status()
            return r.json()

    async def move_absolute_cartesian_base(
        self, pos: Sequence[float], ori: Sequence[float]
    ) -> dict[str, Any]:
        """POST /api/move/absolute_cartesian_base {pos:[x,y,z], ori:[roll,pitch,yaw]}."""
        body = {"pos": _as_xyz(pos, "pos"), "ori": _as_xyz(ori, "ori")}
        if self.mode == "stub":
            return {"success": True, "message": "stub", **body}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                f"{self.base_url}/api/move/absolute_cartesian_base", json=body
            )
            r.raise_for_status()
            return r.json()

    async def move_relative_cartesian_base(
        self, pos: Sequence[float], ori: Sequence[float]
    ) -> dict[str, Any]:
        """POST /api/move/relative_cartesian_base."""
        body = {"pos": _as_xyz(pos, "pos"), "ori": _as_xyz(ori, "ori")}
        if self.mode == "stub":
            return {"success": True, "message": "stub", **body}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                f"{self.base_url}/api/move/relative_cartesian_base", json=body
            )
            r.raise_for_status()
            return r.json()
