"""Chance / Community Chest effect dispatcher (PRD §7.3.6, §5.5).

Effects are structured JSON (see game/chance.json, game/community_chest.json)
so the rules engine applies them deterministically — no LLM interpretation.

Each `apply_*` returns a small result dict that callers use as the
payload for WS events.
"""

from __future__ import annotations

from typing import Any

from game.boards import Board
from game.state import GameState, Player


class EffectError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---- individual effects ----------------------------------------------------


def collect(state: GameState, player: Player, amount: int) -> dict[str, Any]:
    state.players[player].balance += amount
    return {"kind": "collect", "player": player, "amount": amount,
            "balance": state.players[player].balance}


def pay(state: GameState, player: Player, amount: int, *, to: str) -> dict[str, Any]:
    """`to` is 'bank' or 'opponent'. Negative balance is allowed here —
    rules.resolve_bankruptcy owns the bankruptcy trigger."""
    payee = None
    if to == "opponent":
        payee = state.other(player)
        state.players[payee].balance += amount
    state.players[player].balance -= amount
    return {"kind": "pay", "player": player, "amount": amount, "to": to,
            "payee": payee,
            "balance": state.players[player].balance}


def pay_each_player(state: GameState, player: Player, amount: int) -> dict[str, Any]:
    """1v1 game: pay the opponent `amount`."""
    return pay(state, player, amount, to="opponent")


def collect_from_each_player(state: GameState, player: Player, amount: int) -> dict[str, Any]:
    opp = state.other(player)
    state.players[opp].balance -= amount
    state.players[player].balance += amount
    return {"kind": "collect_from_each_player", "player": player, "amount": amount,
            "balance": state.players[player].balance}


def pay_per_building(
    state: GameState, board: Board, player: Player, *, per_house: int, per_hotel: int
) -> dict[str, Any]:
    houses = 0
    hotels = 0
    for p in state.properties.values():
        if p.owner != player:
            continue
        if p.has_hotel:
            hotels += 1
        houses += p.houses
    total = houses * per_house + hotels * per_hotel
    state.players[player].balance -= total
    return {"kind": "pay_per_building", "player": player, "houses": houses,
            "hotels": hotels, "amount": total,
            "balance": state.players[player].balance}


def move_to_tile(
    state: GameState,
    board: Board,
    player: Player,
    *,
    tile_index: int,
    collect_on_pass: bool,
    start_bonus: int,
) -> dict[str, Any]:
    current = state.positions[player]
    # Chance/CC "Advance to X" cards always move forward; we passed START
    # only when the destination index is strictly less than where we were.
    wrapped = tile_index < current
    state.positions[player] = tile_index
    collected = 0
    if wrapped and collect_on_pass and start_bonus > 0:
        collected = start_bonus
        state.players[player].balance += collected
    return {"kind": "move_to_tile", "player": player, "from": current,
            "to": tile_index, "passed_start": wrapped, "collected": collected}


def move_relative(
    state: GameState, board: Board, player: Player, *, delta: int
) -> dict[str, Any]:
    size = board.tile_count
    current = state.positions[player]
    nxt = (current + delta) % size
    state.positions[player] = nxt
    return {"kind": "move_relative", "player": player, "from": current, "to": nxt,
            "delta": delta}


def move_to_nearest(
    state: GameState, board: Board, player: Player, *, kind: str,
    collect_on_pass: bool, start_bonus: int,
) -> dict[str, Any]:
    size = board.tile_count
    current = state.positions[player]
    target = None
    for step in range(1, size + 1):
        cand = (current + step) % size
        if board.tiles[cand].kind == kind:
            target = cand
            break
    if target is None:
        return {"kind": "move_to_nearest", "player": player, "found": False}
    return {
        **move_to_tile(
            state, board, player,
            tile_index=target, collect_on_pass=collect_on_pass, start_bonus=start_bonus,
        ),
        "kind": "move_to_nearest",
        "target_kind": kind,
    }


def grant_jail_free_card(state: GameState, player: Player) -> dict[str, Any]:
    state.players[player].has_jail_free_card = True
    return {"kind": "grant_jail_free_card", "player": player}


def go_to_jail(state: GameState, board: Board, player: Player) -> dict[str, Any]:
    """Move the player to jail_visit. The in_jail FSM lands in M3 (PRD
    §7.3.1); until then no board has an exit mechanism, so go_to_jail
    is a pure teleport and we deliberately do not set the in_jail flag.
    """
    jail_visit = next((t.index for t in board.tiles if t.kind == "jail_visit"), None)
    if jail_visit is None:
        return {"kind": "go_to_jail", "player": player, "found": False}
    current = state.positions[player]
    state.positions[player] = jail_visit
    return {"kind": "go_to_jail", "player": player, "from": current, "to": jail_visit,
            "jail_fsm": False}


# ---- dispatcher ------------------------------------------------------------


def _require(effect: dict[str, Any], key: str) -> Any:
    if key not in effect:
        raise EffectError("BAD_REQUEST", f"effect missing required field: {key!r}")
    return effect[key]


def apply_effect(
    state: GameState, board: Board, player: Player, effect: dict[str, Any],
) -> dict[str, Any]:
    etype = effect.get("type")
    bonus = board.start_bonus
    try:
        if etype == "collect":
            return collect(state, player, int(_require(effect, "amount")))
        if etype == "pay":
            return pay(state, player, int(_require(effect, "amount")),
                       to=effect.get("to", "bank"))
        if etype == "pay_each_player":
            return pay_each_player(state, player, int(_require(effect, "amount")))
        if etype == "collect_from_each_player":
            return collect_from_each_player(state, player, int(_require(effect, "amount")))
        if etype == "pay_per_building":
            return pay_per_building(
                state, board, player,
                per_house=int(_require(effect, "per_house")),
                per_hotel=int(_require(effect, "per_hotel")),
            )
        if etype == "move_to_tile":
            return move_to_tile(
                state, board, player,
                tile_index=int(_require(effect, "tile_index")),
                collect_on_pass=bool(effect.get("collect_on_pass", False)),
                start_bonus=bonus,
            )
        if etype == "move_relative":
            return move_relative(state, board, player,
                                  delta=int(_require(effect, "delta")))
        if etype == "move_to_nearest":
            return move_to_nearest(
                state, board, player,
                kind=_require(effect, "kind"),
                collect_on_pass=True,
                start_bonus=bonus,
            )
        if etype == "grant_jail_free_card":
            return grant_jail_free_card(state, player)
        if etype == "go_to_jail":
            return go_to_jail(state, board, player)
    except (TypeError, ValueError) as exc:
        raise EffectError("BAD_REQUEST", f"invalid arg in {etype!r}: {exc}") from exc
    raise EffectError("BAD_REQUEST", f"unknown effect type: {etype!r}")
