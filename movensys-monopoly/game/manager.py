"""Game manager — serialises FSM transitions (PRD §11.2).

Wraps GameState with an asyncio.Lock so concurrent REST calls don't race
on state mutations. Emits structured WS events around every transition.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from game import rules
from game.boards import load_board
from game.events import EventBus
from game.state import FSM, GameState, Player, RuntimeConfig

log = logging.getLogger("monopoly.game")


class GameManager:
    def __init__(self, bus: EventBus | None = None) -> None:
        self.state: GameState = GameState()
        self.bus: EventBus = bus or EventBus()
        self._lock: asyncio.Lock = asyncio.Lock()

    # ---- public API --------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self.state.model_dump()

    async def start_game(self, board_id: str) -> dict[str, Any]:
        async with self._lock:
            prev = self.state.fsm
            rules.start_game(self.state, board_id)
            self.bus.publish_nowait("game_started", {"board_id": board_id})
            self._emit_transition(prev, self.state.fsm, trigger="start_game")
            log.info("game_started", extra={"board_id": board_id})
            return {"fsm": self.state.fsm.value, "turn": self.state.turn}

    async def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            merged = self.state.config.model_dump()
            merged.update(patch)
            self.state.config = RuntimeConfig.model_validate(merged)
            return self.state.config.model_dump()

    async def request_dice(self) -> dict[str, Any]:
        """Server-side dice acquisition based on dice_source config (PRD §5.2)."""
        async with self._lock:
            source = self.state.config.dice_source
            if source == "manual":
                # /dice/submit must follow — just echo the source.
                return {"source": "manual"}
            if source == "rng":
                value = random.randint(1, 6)
                rules.submit_dice(self.state, value)
                self.bus.publish_nowait("dice_submitted", {"value": value, "source": "rng"})
                self._emit_transition(FSM.TURN_START, self.state.fsm, trigger="dice_submitted")
                return {"source": "rng", "value": value}
            # robot source — adapter plumbing lands in M5; fall back to rng for now.
            value = random.randint(1, 6)
            rules.submit_dice(self.state, value)
            self.bus.publish_nowait("dice_submitted", {"value": value, "source": "rng_fallback"})
            self._emit_transition(FSM.TURN_START, self.state.fsm, trigger="dice_submitted")
            return {"source": "rng_fallback", "value": value}

    async def submit_dice(self, value: int | tuple[int, int], source: str) -> dict[str, Any]:
        async with self._lock:
            prev = self.state.fsm
            rules.submit_dice(self.state, value)
            self.bus.publish_nowait(
                "dice_submitted",
                {"value": value, "source": source, "sum": self.state.last_dice_sum},
            )
            self._emit_transition(prev, self.state.fsm, trigger="dice_submitted")
            return {
                "fsm": self.state.fsm.value,
                "dice": list(self.state.last_dice) if self.state.last_dice else None,
                "sum": self.state.last_dice_sum,
            }

    async def apply_move(self, player: Player, from_tile: int, to_tile: int) -> dict[str, Any]:
        async with self._lock:
            prev = self.state.fsm
            result = rules.apply_move(self.state, player, from_tile, to_tile)
            self.bus.publish_nowait(
                "move_applied",
                {
                    "player": result.player,
                    "from_tile": result.from_tile,
                    "to_tile": result.to_tile,
                    "dice_sum": result.dice_sum,
                    "wrapped": result.wrapped,
                },
            )
            if result.wrapped:
                self.bus.publish_nowait("lap_completed", {"player": result.player})
            self._emit_transition(prev, self.state.fsm, trigger="move_applied")
            if result.winner is not None:
                self.bus.publish_nowait("game_won", {"winner": result.winner})
                log.info("game_won", extra={"winner": result.winner})
            return {
                "fsm": self.state.fsm.value,
                "resolved": {
                    "player": result.player,
                    "to_tile": result.to_tile,
                    "wrapped": result.wrapped,
                    "winner": result.winner,
                },
            }

    async def end_turn(self) -> dict[str, Any]:
        async with self._lock:
            prev = self.state.fsm
            rules.end_turn(self.state)
            self._emit_transition(prev, self.state.fsm, trigger="end_turn")
            return {"fsm": self.state.fsm.value, "turn": self.state.turn}

    def winner(self) -> Player | None:
        return self.state.winner

    # ---- helpers -----------------------------------------------------------

    def _emit_transition(self, prev: FSM, nxt: FSM, trigger: str) -> None:
        if prev == nxt:
            return
        self.bus.publish_nowait(
            "fsm_transition",
            {"from": prev.value, "to": nxt.value, "trigger": trigger},
        )
