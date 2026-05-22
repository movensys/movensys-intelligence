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


# Spec §4.1.3, §4.2.2: rent = the cumulative buy cost for the opponent's
# current tier ($100 land, $200 house, $300 hotel). Utilities cap at land.
_RENT_BY_TIER = {1: 150, 2: 300, 3: 450}


def compute_rent(
    state: GameState, board: Board, tile_index: int, dice_sum: int | None
) -> int:
    """Rent to pay when landing on `tile_index` owned by someone.

    Returns 0 when unowned, self-owned, or when the tile isn't a buyable
    kind. `dice_sum` is accepted for back-compat but no longer used
    (utility rent is now flat $100, same as land).
    """
    tile = board.tiles[tile_index]
    if tile.kind not in ("property", "railroad", "utility"):
        return 0
    pid = property_id(board.board_id, tile.name)
    p = state.properties.get(pid)
    if p is None or p.owner is None or p.mortgaged:
        return 0
    if p.has_hotel:
        tier = 3
    elif p.houses > 0:
        tier = 2
    else:
        tier = 1
    return _RENT_BY_TIER[tier]


# ---- projection to PRD §4.4 PropertyCard shape ----------------------------


def render_card(tile: Tile, p: PropertyState, board_id: str) -> dict:
    """Merge static + dynamic view for REST responses (PRD §4.4).

    The per-tile `price_buy` / `price_building` / `rent_table` fields
    are no longer relevant under the flat-economy spec; the UI uses
    the global $100/$200/$300 ladder.
    """
    return {
        "id": p.id,
        "tile_index": tile.index,
        "name": tile.name,
        "kind": tile.kind,
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
