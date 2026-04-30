"""Rent computation and property helpers (PRD §7.3).

Static tile data lives in `game/boards.Board.tiles`. Dynamic ownership
(owner, houses, mortgaged) lives in `GameState.properties`. This module
stitches them together.
"""

from __future__ import annotations

import re
from typing import Iterable

from game.boards import Board, Tile
from game.state import GameState, Player, PropertyState

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(name: str) -> str:
    return _SLUG_RE.sub("_", name.lower()).strip("_")


def property_id(board_id: str, tile_name: str) -> str:
    return f"board{board_id}:{slug(tile_name)}"


def initial_properties(board: Board) -> dict[str, PropertyState]:
    """Build the dynamic map keyed by property_id for a fresh game."""
    out: dict[str, PropertyState] = {}
    for tile in board.tiles:
        if tile.kind not in ("property", "railroad", "utility"):
            continue
        pid = property_id(board.board_id, tile.name)
        out[pid] = PropertyState(id=pid, tile_index=tile.index)
    return out


# ---- ownership queries -----------------------------------------------------


def owned_by(state: GameState, owner: Player) -> list[PropertyState]:
    return [p for p in state.properties.values() if p.owner == owner]


def is_monopoly(state: GameState, board: Board, color_group: str, owner: Player) -> bool:
    """Player owns every tile in the color group (PRD §7.3.5)."""
    if not color_group:
        return False
    group_tiles = [t for t in board.tiles if t.kind == "property" and t.color_group == color_group]
    if not group_tiles:
        return False
    for tile in group_tiles:
        pid = property_id(board.board_id, tile.name)
        state_p = state.properties.get(pid)
        if state_p is None or state_p.owner != owner:
            return False
    return True


def railroads_owned(state: GameState, board: Board, owner: Player) -> int:
    return sum(
        1
        for tile in board.tiles
        if tile.kind == "railroad"
        and (p := state.properties.get(property_id(board.board_id, tile.name))) is not None
        and p.owner == owner
    )


def utilities_owned(state: GameState, board: Board, owner: Player) -> int:
    return sum(
        1
        for tile in board.tiles
        if tile.kind == "utility"
        and (p := state.properties.get(property_id(board.board_id, tile.name))) is not None
        and p.owner == owner
    )


# ---- rent computation ------------------------------------------------------


def compute_rent(
    state: GameState, board: Board, tile_index: int, dice_sum: int | None
) -> int:
    """Rent to pay when landing on `tile_index` owned by someone.

    Returns 0 when unowned, self-owned, mortgaged, or when the tile is
    not a purchasable kind.
    """
    tile = board.tiles[tile_index]
    if tile.kind not in ("property", "railroad", "utility"):
        return 0
    pid = property_id(board.board_id, tile.name)
    p = state.properties.get(pid)
    if p is None or p.owner is None or p.mortgaged:
        return 0

    if tile.kind == "property":
        return _rent_property(tile, p, board, state)
    if tile.kind == "railroad":
        n = railroads_owned(state, board, p.owner)
        return 25 * (2 ** (n - 1)) if n > 0 else 0
    # utility
    if dice_sum is None:
        return 0
    n = utilities_owned(state, board, p.owner)
    factor = 10 if n >= 2 else 4
    return dice_sum * factor


def _rent_property(tile: Tile, p: PropertyState, board: Board, state: GameState) -> int:
    rents = tile.rent_table or [0]
    if p.has_hotel:
        return rents[5] if len(rents) > 5 else rents[-1]
    if p.houses > 0:
        idx = min(p.houses, len(rents) - 1)
        return rents[idx]
    base = rents[0]
    # Monopoly bonus applies only to unimproved properties (§7.3.5).
    if tile.color_group and is_monopoly(state, board, tile.color_group, p.owner):  # type: ignore[arg-type]
        return base * max(1, board.monopoly_bonus_multiplier)
    return base


# ---- even-build rule (PRD §7.3.5) ----------------------------------------


def even_build_ok(
    state: GameState, board: Board, color_group: str, change_pid: str, delta: int
) -> bool:
    """After applying `delta` to `change_pid`, max-min house count in the
    color group must be at most 1 (max one over min).
    """
    houses: list[int] = []
    for tile in board.tiles:
        if tile.kind != "property" or tile.color_group != color_group:
            continue
        pid = property_id(board.board_id, tile.name)
        p = state.properties.get(pid)
        if p is None:
            continue
        h = p.houses + (delta if pid == change_pid else 0)
        if p.has_hotel and pid != change_pid:
            h = 5  # count hotel as houses=5 for the comparison
        if pid == change_pid and p.has_hotel and delta == 0:
            h = 5
        houses.append(h)
    if not houses:
        return True
    return (max(houses) - min(houses)) <= 1


# ---- projection to PRD §4.4 PropertyCard shape ----------------------------


def render_card(tile: Tile, p: PropertyState, board_id: str) -> dict:
    """Merge static + dynamic view for REST responses (PRD §4.4)."""
    return {
        "id": p.id,
        "tile_index": tile.index,
        "name": tile.name,
        "kind": tile.kind,
        "color_group": tile.color_group,
        "price_buy": tile.price_buy,
        "price_building": tile.price_building,
        "rent_table": tile.rent_table,
        "owner": p.owner,
        "houses": p.houses,
        "has_hotel": p.has_hotel,
        "mortgaged": p.mortgaged,
    }


def all_cards(state: GameState, board: Board) -> Iterable[dict]:
    for tile in board.tiles:
        if tile.kind not in ("property", "railroad", "utility"):
            continue
        pid = property_id(board.board_id, tile.name)
        p = state.properties.get(pid)
        if p is None:
            continue
        yield render_card(tile, p, board.board_id)
