"""Canonical game state (PRD §4).

Single source of truth: `GameState`. All REST responses and WS events
project from this. `positions` is the authoritative piece location; the
UI must not display piece positions from WS payloads alone — it should
reconcile against `/api/game/state` on reconnect.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

Player = Literal["user", "robot"]
BoardId = Literal["1", "2", "3"]
DiceSource = Literal["manual", "rng", "robot"]


class FSM(str, Enum):
    IDLE = "IDLE"
    TURN_START = "TURN_START"
    MOVING = "MOVING"
    RESOLVE_TILE = "RESOLVE_TILE"
    AWAIT_DECISION = "AWAIT_DECISION"
    PAY_RENT = "PAY_RENT"
    END_TURN = "END_TURN"
    GAME_OVER = "GAME_OVER"


class PlayerState(BaseModel):
    id: Player
    balance: int = 0
    in_jail: bool = False
    jail_turns_left: int = 0
    has_jail_free_card: bool = False
    color: str = "#888888"


class PropertyState(BaseModel):
    """Dynamic ownership state for a purchasable tile (PRD §4.4).

    Paired with the static `Tile` from `game/boards.py` to form the full
    property card view.
    """

    id: str                          # "board1:baltic_avenue"
    tile_index: int
    owner: Player | None = None
    houses: int = 0                  # 0..4 (property only)
    has_hotel: bool = False
    mortgaged: bool = False


class RuntimeConfig(BaseModel):
    dice_source: DiceSource = "rng"
    auctions_enabled: bool = False
    income_tax_mode: Literal["fixed_200", "choose"] = "fixed_200"
    player_colors: dict[Player, str] = Field(
        default_factory=lambda: {"user": "#E53935", "robot": "#1E88E5"}
    )


class GameState(BaseModel):
    board_id: BoardId = "3"
    fsm: FSM = FSM.IDLE
    turn: Player = "user"
    turn_number: int = 0
    positions: dict[Player, int] = Field(default_factory=dict)
    players: dict[Player, PlayerState] = Field(default_factory=dict)
    properties: dict[str, PropertyState] = Field(default_factory=dict)
    last_dice: tuple[int, int] | None = None
    last_dice_sum: int | None = None
    pending_dice: int | None = None
    doubles_streak: int = 0
    lap_count: dict[Player, int] = Field(default_factory=dict)
    winner: Player | None = None
    config: RuntimeConfig = Field(default_factory=RuntimeConfig)

    def is_active(self) -> bool:
        return self.fsm not in (FSM.IDLE, FSM.GAME_OVER)

    def other(self, p: Player) -> Player:
        return "robot" if p == "user" else "user"
