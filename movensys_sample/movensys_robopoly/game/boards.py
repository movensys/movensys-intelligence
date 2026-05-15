"""Board tile loader (PRD §7, §4.4).

Reads board JSON from static/assets/boards/board{id}.json and validates
the tile list against pydantic schemas. Loaded once and cached.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

TileKind = Literal[
    "start",
    "property",
    "railroad",
    "utility",
    "tax",
    "chance",
    "community_chest",
    "jail_visit",
    "go_to_jail",
    "free_parking",
    "blank",
]


class Tile(BaseModel):
    index: int
    kind: TileKind
    name: str = ""
    price_buy: int | None = None
    price_building: int | None = None
    rent_table: list[int] | None = None
    amount: int | None = None


class BoardLayout(BaseModel):
    shape: str | None = None
    columns: int | None = None
    rows: int | None = None


class Board(BaseModel):
    board_id: str
    tile_count: int
    seed_money: int = 0
    start_bonus: int = 0
    tiles: list[Tile]
    layout: BoardLayout | None = None
    physical_image: str | None = None
    blank_svg: str | None = None

    def tile(self, index: int) -> Tile:
        return self.tiles[index % self.tile_count]


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "assets" / "boards"


@lru_cache(maxsize=4)
def load_board(board_id: str) -> Board:
    path = _assets_dir() / f"board_{board_id}.json"
    data = path.read_text()
    return Board.model_validate_json(data)
