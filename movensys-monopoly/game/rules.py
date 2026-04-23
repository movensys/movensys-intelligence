"""Game rule engine (PRD §7).

M1 scope: Board 3 smoke path only.
- `start_game`  : initialise GameState for a board
- `submit_dice` : register a dice roll, transition IDLE/TURN_START -> MOVING
- `apply_move`  : validate against expected tile, advance FSM, detect lap wrap
- `end_turn`    : rotate turn, back to TURN_START (unless GAME_OVER)

Subsequent milestones extend this with property resolution (M2) and
Board 2 specials: jail, railroad, utility, tax, monopoly bonus, community
chest, mortgage (M3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from game.boards import Board, load_board
from game.state import FSM, GameState, Player, PlayerState


class RuleError(ValueError):
    """Raised when a request violates game rules. Mapped to 409 by the API."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


# ---- helpers ---------------------------------------------------------------


def _init_players(state: GameState, board: Board) -> None:
    colors = state.config.player_colors
    for pid in ("user", "robot"):
        state.players[pid] = PlayerState(
            id=pid, balance=board.seed_money, color=colors.get(pid, "#888")
        )
        state.positions[pid] = 0
        state.lap_count[pid] = 0


# ---- transitions -----------------------------------------------------------


def start_game(state: GameState, board_id: str) -> Board:
    if state.fsm not in (FSM.IDLE, FSM.GAME_OVER):
        raise RuleError("INVALID_STATE", f"cannot start while fsm={state.fsm.value}")
    if board_id not in ("1", "2", "3"):
        raise RuleError("BAD_REQUEST", f"unknown board_id: {board_id!r}")
    board = load_board(board_id)
    state.board_id = board_id  # type: ignore[assignment]
    state.fsm = FSM.TURN_START
    state.turn = "user"
    state.turn_number = 1
    state.last_dice = None
    state.last_dice_sum = None
    state.pending_dice = None
    state.doubles_streak = 0
    state.winner = None
    state.players.clear()
    state.positions.clear()
    state.lap_count.clear()
    _init_players(state, board)
    return board


def submit_dice(state: GameState, value: int | tuple[int, int]) -> None:
    if state.fsm != FSM.TURN_START:
        raise RuleError("INVALID_STATE", f"cannot submit dice in fsm={state.fsm.value}")
    if isinstance(value, tuple):
        d1, d2 = value
        if not (1 <= d1 <= 6 and 1 <= d2 <= 6):
            raise RuleError("BAD_REQUEST", f"dice out of range: {value}")
        total = d1 + d2
        state.last_dice = (d1, d2)
    else:
        if not (1 <= value <= 6):
            raise RuleError("BAD_REQUEST", f"dice out of range: {value}")
        total = value
        state.last_dice = (value, 0)
    state.last_dice_sum = total
    state.pending_dice = total
    state.fsm = FSM.MOVING


@dataclass
class MoveResult:
    player: Player
    from_tile: int
    to_tile: int
    dice_sum: int
    wrapped: bool          # crossed the START tile
    lap_completed: bool    # this lap is the player's first lap (Board 3 win)
    winner: Player | None  # set if the move ended the game


def apply_move(state: GameState, player: Player, from_tile: int, to_tile: int) -> MoveResult:
    if state.fsm != FSM.MOVING:
        raise RuleError("INVALID_STATE", f"cannot apply move in fsm={state.fsm.value}")
    if player != state.turn:
        raise RuleError("INVALID_STATE", f"not {player}'s turn (turn={state.turn})")
    if state.pending_dice is None:
        raise RuleError("INVALID_STATE", "no pending dice")

    board = load_board(state.board_id)
    size = board.tile_count

    expected_from = state.positions.get(player, 0)
    if from_tile != expected_from:
        raise RuleError(
            "TILE_MISMATCH",
            f"from_tile {from_tile} does not match server position {expected_from}",
            {"from_tile": from_tile, "server": expected_from},
        )

    dice = state.pending_dice
    expected_to = (from_tile + dice) % size
    if to_tile != expected_to:
        raise RuleError(
            "TILE_MISMATCH",
            f"to_tile {to_tile} does not match computed {expected_to}",
            {"dice": dice, "expected_to": expected_to, "given": to_tile},
        )

    wrapped = to_tile < from_tile or (from_tile + dice) >= size
    state.positions[player] = to_tile
    state.pending_dice = None
    state.fsm = FSM.RESOLVE_TILE

    lap_completed = False
    winner: Player | None = None
    if wrapped:
        state.lap_count[player] = state.lap_count.get(player, 0) + 1
        # Board 3 rule: first to complete a full lap wins.
        if board.board_id == "3":
            lap_completed = True
            winner = player
            state.winner = player
            state.fsm = FSM.GAME_OVER

    return MoveResult(
        player=player,
        from_tile=from_tile,
        to_tile=to_tile,
        dice_sum=dice,
        wrapped=wrapped,
        lap_completed=lap_completed,
        winner=winner,
    )


def end_turn(state: GameState) -> None:
    if state.fsm == FSM.GAME_OVER:
        return
    if state.fsm not in (FSM.RESOLVE_TILE, FSM.END_TURN):
        raise RuleError("INVALID_STATE", f"cannot end turn in fsm={state.fsm.value}")
    state.turn = state.other(state.turn)
    state.turn_number += 1
    state.last_dice = None
    state.last_dice_sum = None
    state.pending_dice = None
    state.fsm = FSM.TURN_START
