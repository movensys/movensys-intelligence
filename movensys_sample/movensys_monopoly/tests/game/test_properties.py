"""Property / rent computation tests (PRD §7.3)."""

from __future__ import annotations

import pytest

from game.boards import load_board
from game.properties import (
    compute_rent,
    even_build_ok,
    initial_properties,
    is_monopoly,
    property_id,
    railroads_owned,
    utilities_owned,
)
from game.state import GameState, PropertyState


@pytest.fixture
def board2_state() -> tuple[GameState, "Board"]:  # type: ignore[name-defined]
    board = load_board("2")
    state = GameState(board_id="2", properties=initial_properties(board))
    return state, board


def _own(state: GameState, pid: str, owner: str = "user", houses: int = 0, hotel: bool = False, mortgaged: bool = False) -> None:
    p = state.properties[pid]
    p.owner = owner
    p.houses = houses
    p.has_hotel = hotel
    p.mortgaged = mortgaged


# ---- unowned / self / mortgaged -------------------------------------------


def test_rent_zero_when_unowned(board2_state) -> None:
    state, board = board2_state
    assert compute_rent(state, board, 1, dice_sum=6) == 0  # Mediterranean


def test_rent_zero_when_mortgaged(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue", mortgaged=True)
    assert compute_rent(state, board, 1, dice_sum=6) == 0


# ---- property rent ---------------------------------------------------------


def test_base_rent_property(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue")   # brown group, other tile unowned
    assert compute_rent(state, board, 1, dice_sum=None) == 2  # rent_table[0]


def test_monopoly_doubles_unimproved_rent(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue")
    _own(state, "board2:baltic_avenue")
    # brown monopoly: mediterranean base rent 2 -> 4, baltic 4 -> 8
    assert compute_rent(state, board, 1, None) == 4
    assert compute_rent(state, board, 3, None) == 8


def test_monopoly_does_not_double_when_houses_present(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue", houses=1)
    _own(state, "board2:baltic_avenue")
    # mediterranean has 1 house -> use rent_table[1], not base*2
    assert compute_rent(state, board, 1, None) == 10


def test_hotel_rent(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:boardwalk", hotel=True)
    # Boardwalk hotel = 2000 per Hasbro table
    assert compute_rent(state, board, 39, None) == 2000


# ---- railroad --------------------------------------------------------------


@pytest.mark.parametrize("owned,expected", [(1, 25), (2, 50), (3, 100), (4, 200)])
def test_railroad_scaling(board2_state, owned: int, expected: int) -> None:
    state, board = board2_state
    railroads = ["board2:reading_railroad", "board2:pennsylvania_railroad",
                 "board2:b_o_railroad", "board2:short_line"]
    for pid in railroads[:owned]:
        _own(state, pid)
    # Land on Reading (tile 5)
    assert compute_rent(state, board, 5, dice_sum=None) == expected
    assert railroads_owned(state, board, "user") == owned


# ---- utility ---------------------------------------------------------------


def test_utility_one_owned_times_four(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:electric_company")
    # tile 12 Electric Company, dice=7 -> 7*4 = 28
    assert compute_rent(state, board, 12, dice_sum=7) == 28
    assert utilities_owned(state, board, "user") == 1


def test_utility_both_owned_times_ten(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:electric_company")
    _own(state, "board2:water_works")
    assert compute_rent(state, board, 28, dice_sum=6) == 60


def test_utility_without_dice_sum_returns_zero(board2_state) -> None:
    """compute_rent must never crash when called without dice context —
    some paths (e.g. snapshot endpoints) won't know the dice."""
    state, board = board2_state
    _own(state, "board2:electric_company")
    assert compute_rent(state, board, 12, dice_sum=None) == 0


# ---- monopoly detection ----------------------------------------------------


def test_is_monopoly_happy_path(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue")
    _own(state, "board2:baltic_avenue")
    assert is_monopoly(state, board, "brown", "user") is True


def test_is_monopoly_partial(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue")
    assert is_monopoly(state, board, "brown", "user") is False


def test_is_monopoly_split_owners(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue", owner="user")
    _own(state, "board2:baltic_avenue", owner="robot")
    assert is_monopoly(state, board, "brown", "user") is False
    assert is_monopoly(state, board, "brown", "robot") is False


# ---- even-build rule ------------------------------------------------------


def test_even_build_allowed_within_one(board2_state) -> None:
    state, board = board2_state
    for pid in ("board2:mediterranean_avenue", "board2:baltic_avenue"):
        _own(state, pid, houses=1)
    # Adding a house to baltic makes [1, 2] -> diff 1 -> OK
    assert even_build_ok(state, board, "brown", "board2:baltic_avenue", +1) is True


def test_even_build_blocks_two_gap(board2_state) -> None:
    state, board = board2_state
    _own(state, "board2:mediterranean_avenue", houses=1)
    _own(state, "board2:baltic_avenue", houses=1)
    # Adding two to baltic would be +2 over mediterranean -> diff 2 -> BLOCK
    # test with delta=+2 via artificial single call
    state.properties["board2:baltic_avenue"].houses = 2
    assert even_build_ok(state, board, "brown", "board2:baltic_avenue", +1) is False


# ---- Board 1 sanity --------------------------------------------------------


def test_board1_single_tile_group_gets_monopoly_bonus() -> None:
    """Board 1 uses monopoly_bonus_multiplier=2 and each color group is a
    single tile, so owning one tile trivially owns the group and the
    base rent doubles."""
    board = load_board("1")
    state = GameState(board_id="1", properties=initial_properties(board))
    _own(state, "board1:baltic_avenue")
    # Baltic base rent 4 * 2 = 8
    assert compute_rent(state, board, 1, None) == 8


def test_property_id_slug_stability() -> None:
    assert property_id("2", "B&O Railroad") == "board2:b_o_railroad"
    assert property_id("2", "Park Place") == "board2:park_place"
    assert property_id("2", "St. Charles Place") == "board2:st_charles_place"
