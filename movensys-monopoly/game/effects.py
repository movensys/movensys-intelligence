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
    """Move the player to jail_visit. Only sets the in_jail flag when the
    board actually enforces a jail FSM (Board 2, monopoly_bonus_multiplier > 1).
    Board 1's short game does not have jail exit mechanics, so the teleport
    alone is the full behaviour (PRD §7.3.1 lands in M3).
    """
    jail_visit = next((t.index for t in board.tiles if t.kind == "jail_visit"), None)
    if jail_visit is None:
        return {"kind": "go_to_jail", "player": player, "found": False}
    current = state.positions[player]
    state.positions[player] = jail_visit
    jail_fsm = board.monopoly_bonus_multiplier > 1  # Board 2 only, for now
    if jail_fsm:
        state.players[player].in_jail = True
        state.players[player].jail_turns_left = 3
    return {"kind": "go_to_jail", "player": player, "from": current, "to": jail_visit,
            "jail_fsm": jail_fsm}


# ---- dispatcher ------------------------------------------------------------


def apply_effect(
    state: GameState, board: Board, player: Player, effect: dict[str, Any],
) -> dict[str, Any]:
    etype = effect.get("type")
    bonus = board.start_bonus
    if etype == "collect":
        return collect(state, player, int(effect["amount"]))
    if etype == "pay":
        return pay(state, player, int(effect["amount"]), to=effect.get("to", "bank"))
    if etype == "pay_each_player":
        return pay_each_player(state, player, int(effect["amount"]))
    if etype == "collect_from_each_player":
        return collect_from_each_player(state, player, int(effect["amount"]))
    if etype == "pay_per_building":
        return pay_per_building(
            state, board, player,
            per_house=int(effect["per_house"]), per_hotel=int(effect["per_hotel"]),
        )
    if etype == "move_to_tile":
        return move_to_tile(
            state, board, player,
            tile_index=int(effect["tile_index"]),
            collect_on_pass=bool(effect.get("collect_on_pass", False)),
            start_bonus=bonus,
        )
    if etype == "move_relative":
        return move_relative(state, board, player, delta=int(effect["delta"]))
    if etype == "move_to_nearest":
        return move_to_nearest(
            state, board, player,
            kind=effect["kind"],
            collect_on_pass=True,
            start_bonus=bonus,
        )
    if etype == "grant_jail_free_card":
        return grant_jail_free_card(state, player)
    if etype == "go_to_jail":
        return go_to_jail(state, board, player)
    raise EffectError("BAD_REQUEST", f"unknown effect type: {etype!r}")
