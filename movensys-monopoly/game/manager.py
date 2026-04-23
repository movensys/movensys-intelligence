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
from game.decks import Deck, load_chance, load_community_chest
from game.effects import EffectError, apply_effect
from game.events import EventBus
from game.properties import all_cards as _all_cards
from game.properties import property_id as _property_id
from game.state import FSM, GameState, Player, RuntimeConfig

log = logging.getLogger("monopoly.game")


class GameManager:
    def __init__(self, bus: EventBus | None = None) -> None:
        self.state: GameState = GameState()
        self.bus: EventBus = bus or EventBus()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._chance: Deck | None = None
        self._cc: Deck | None = None

    # ---- public API --------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self.state.model_dump()

    async def start_game(self, board_id: str) -> dict[str, Any]:
        async with self._lock:
            prev = self.state.fsm
            rules.start_game(self.state, board_id)
            self._chance = load_chance()
            self._cc = load_community_chest()
            self._chance.shuffle()
            self._cc.shuffle()
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
                if result.start_bonus_collected > 0:
                    self.bus.publish_nowait("start_bonus", {
                        "player": result.player,
                        "amount": result.start_bonus_collected,
                        "balance": self.state.players[result.player].balance,
                    })
            self._emit_transition(prev, self.state.fsm, trigger="move_applied")

            resolved = []
            if result.winner is None and self.state.fsm == FSM.RESOLVE_TILE:
                board = load_board(self.state.board_id)
                tile_results = rules.resolve_tile(
                    self.state, board, player,
                    chance_deck=self._chance, cc_deck=self._cc,
                )
                for r in tile_results:
                    # Narrate auto-liquidation so the UI can render each sale
                    # before the final rent/tax settlement.
                    for step in r.payload.get("liquidation", []) or []:
                        self.bus.publish_nowait(step.get("kind", "liquidation_step"), step)
                    self.bus.publish_nowait(f"tile_{r.kind}", {
                        "tile_index": r.tile_index,
                        "needs_decision": r.needs_decision,
                        **r.payload,
                    })
                    resolved.append({
                        "kind": r.kind,
                        "tile_index": r.tile_index,
                        "needs_decision": r.needs_decision,
                        "payload": r.payload,
                    })
                if self.state.fsm == FSM.GAME_OVER and self.state.winner:
                    self.bus.publish_nowait("game_won", {"winner": self.state.winner})

            if result.winner is not None:
                self.bus.publish_nowait("game_won", {"winner": result.winner})
                log.info("game_won", extra={"winner": result.winner})

            return {
                "fsm": self.state.fsm.value,
                "resolved": {
                    "player": result.player,
                    "to_tile": result.to_tile,
                    "wrapped": result.wrapped,
                    "winner": result.winner or self.state.winner,
                    "tiles": resolved,
                },
            }

    # ---- property transactions ---------------------------------------------

    async def buy_property(self, player: Player, pid: str) -> dict[str, Any]:
        async with self._lock:
            board = load_board(self.state.board_id)
            prev = self.state.fsm
            res = rules.buy_property(self.state, board, player, pid)
            self.bus.publish_nowait("property_bought", res)
            self._emit_transition(prev, self.state.fsm, trigger="buy_property")
            return res

    async def skip_purchase(self) -> dict[str, Any]:
        async with self._lock:
            prev = self.state.fsm
            rules.skip_purchase(self.state)
            self.bus.publish_nowait("purchase_skipped", {})
            self._emit_transition(prev, self.state.fsm, trigger="skip_purchase")
            return {"fsm": self.state.fsm.value}

    async def decide_property(
        self, player: Player, pid: str, action: str, house_count: int = 0,
    ) -> dict[str, Any]:
        async with self._lock:
            board = load_board(self.state.board_id)
            prev = self.state.fsm
            if action == "skip":
                rules.skip_purchase(self.state)
                self.bus.publish_nowait("purchase_skipped", {"property_id": pid})
                self._emit_transition(prev, self.state.fsm, trigger="decide_skip")
                return {"action": "skip", "fsm": self.state.fsm.value}
            if action == "buy":
                res = rules.buy_property(self.state, board, player, pid)
                self.bus.publish_nowait("property_bought", res)
                self._emit_transition(prev, self.state.fsm, trigger="decide_buy")
                return {"action": "buy", **res, "fsm": self.state.fsm.value}
            if action == "build":
                res = rules.buy_property(self.state, board, player, pid)
                self.bus.publish_nowait("property_bought", res)
                for _ in range(max(1, house_count)):
                    try:
                        built = rules.build(self.state, board, player, pid)
                        self.bus.publish_nowait("property_built", built)
                    except rules.RuleError as exc:
                        self.bus.publish_nowait(
                            "property_build_rejected",
                            {"property_id": pid, "code": exc.code, "message": str(exc)},
                        )
                        break
                self._emit_transition(prev, self.state.fsm, trigger="decide_build")
                return {"action": "build", "fsm": self.state.fsm.value}
            raise rules.RuleError("BAD_REQUEST", f"unknown action: {action!r}")

    async def build(
        self, player: Player, pid: str, *, houses: int = 1, hotel: bool = False,
    ) -> dict[str, Any]:
        async with self._lock:
            board = load_board(self.state.board_id)
            res = rules.build(self.state, board, player, pid, houses=houses, hotel=hotel)
            self.bus.publish_nowait("property_built", res)
            return res

    async def mortgage(self, player: Player, pid: str) -> dict[str, Any]:
        async with self._lock:
            board = load_board(self.state.board_id)
            res = rules.mortgage(self.state, board, player, pid)
            self.bus.publish_nowait("property_mortgaged", res)
            return res

    async def unmortgage(self, player: Player, pid: str) -> dict[str, Any]:
        async with self._lock:
            board = load_board(self.state.board_id)
            res = rules.unmortgage(self.state, board, player, pid)
            self.bus.publish_nowait("property_unmortgaged", res)
            return res

    async def sell_building(self, player: Player, pid: str) -> dict[str, Any]:
        async with self._lock:
            board = load_board(self.state.board_id)
            res = rules.sell_building(self.state, board, player, pid)
            self.bus.publish_nowait("building_sold", res)
            return res

    async def apply_card_effect(self, player: Player, effect: dict[str, Any]) -> dict[str, Any]:
        """Used by /api/effects/* endpoints (PRD §5.5). These mirror what a
        Chance/CC card effect would do, callable from the UI for testing."""
        async with self._lock:
            board = load_board(self.state.board_id)
            res = apply_effect(self.state, board, player, effect)
            self.bus.publish_nowait("effect_applied", res)
            return res

    def list_properties(self) -> list[dict[str, Any]]:
        if self.state.board_id not in ("1", "2"):
            return []
        return list(_all_cards(self.state, load_board(self.state.board_id)))

    def money_snapshot(self) -> dict[str, int]:
        return {pid: p.balance for pid, p in self.state.players.items()}

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
