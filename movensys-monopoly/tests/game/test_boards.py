from __future__ import annotations

import pytest

from game.boards import load_board


@pytest.mark.parametrize("board_id,expected_tiles", [("1", 16), ("2", 40), ("3", 12)])
def test_load_board_tile_counts(board_id: str, expected_tiles: int) -> None:
    board = load_board(board_id)
    assert board.board_id == board_id
    assert board.tile_count == expected_tiles
    assert len(board.tiles) == expected_tiles
    for i, tile in enumerate(board.tiles):
        assert tile.index == i


def test_board2_has_canonical_features() -> None:
    board = load_board("2")
    kinds = {t.kind for t in board.tiles}
    assert {"start", "property", "railroad", "utility", "tax",
            "chance", "community_chest", "jail_visit", "go_to_jail",
            "free_parking"} <= kinds
    # 28 purchasable (22 property + 4 railroad + 2 utility)
    purchasable = [t for t in board.tiles if t.kind in ("property", "railroad", "utility")]
    assert len(purchasable) == 28


def test_board3_is_all_blank_plus_start() -> None:
    board = load_board("3")
    assert board.tiles[0].kind == "start"
    assert all(t.kind == "blank" for t in board.tiles[1:])
    assert board.seed_money == 0


def test_load_board_is_cached() -> None:
    b1 = load_board("3")
    b2 = load_board("3")
    assert b1 is b2
