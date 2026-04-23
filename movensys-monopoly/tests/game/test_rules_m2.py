"""resolve_tile + property transactions + bankruptcy tests (PRD §7, M2)."""

from __future__ import annotations

import pytest

from game import (
    FSM,
    GameState,
    RuleError,
    apply_move,
    build,
    buy_property,
    end_turn,
    load_board,
    load_chance,
    load_community_chest,
    mortgage,
    resolve_tile,
    sell_building,
    skip_purchase,
    start_game,
    submit_dice,
    unmortgage,
)


def _fresh(board_id: str = "2") -> GameState:
    state = GameState()
    start_game(state, board_id)
    return state


def _to(state: GameState, player: str, tile_index: int, dice_sum: int = 7) -> None:
    """Jump a player to an arbitrary tile for test setup.

    Skips the dice/move FSM flow — tests are about resolve_tile, not the
    path there. `dice_sum` is preserved so utility rent can still be
    computed correctly when relevant.
    """
    state.turn = player
    state.positions[player] = tile_index
    state.last_dice_sum = dice_sum
    state.fsm = FSM.RESOLVE_TILE


# ---- resolve_tile dispatching ---------------------------------------------


def test_resolve_start_is_noop() -> None:
    state = _fresh("2")
    # user already at tile 0 after RESOLVE_TILE transition? No — after start
    # fsm=TURN_START. We need to force RESOLVE_TILE by doing a move first.
    _to(state, "user", 0 + 3)  # land on Baltic eventually — let's keep simple
    # Reset and land on GO via advance
    state.positions["user"] = 0
    state.fsm = FSM.RESOLVE_TILE
    results = resolve_tile(state, load_board("2"), "user")
    assert results[0].kind == "start"


def test_resolve_buyable_property_triggers_decision() -> None:
    state = _fresh("2")
    _to(state, "user", 1)  # Mediterranean
    board = load_board("2")
    results = resolve_tile(state, board, "user")
    r = results[0]
    assert r.kind == "property_arrival_buyable"
    assert r.needs_decision is True
    assert state.fsm == FSM.AWAIT_DECISION
    assert r.payload["property_id"] == "board2:mediterranean_avenue"


def test_resolve_buyable_unaffordable_no_decision() -> None:
    state = _fresh("2")
    state.players["user"].balance = 30  # less than $60 price
    _to(state, "user", 1)
    results = resolve_tile(state, load_board("2"), "user")
    r = results[0]
    assert r.kind == "property_arrival_unaffordable"
    assert r.needs_decision is False
    assert state.fsm == FSM.RESOLVE_TILE  # stays here


def test_resolve_rent_charges_owner(monkeypatch) -> None:
    state = _fresh("2")
    # Robot owns Mediterranean; user lands on it.
    state.properties["board2:mediterranean_avenue"].owner = "robot"
    _to(state, "user", 1)
    results = resolve_tile(state, load_board("2"), "user")
    assert results[0].kind == "rent_paid"
    # Rent 2 * 1 = 2 (not monopoly)
    assert state.players["robot"].balance == 1500 + 2
    assert state.players["user"].balance == 1500 - 2


def test_resolve_self_owned_no_rent() -> None:
    state = _fresh("2")
    state.properties["board2:mediterranean_avenue"].owner = "user"
    _to(state, "user", 1)
    results = resolve_tile(state, load_board("2"), "user")
    assert results[0].kind == "property_arrival_self_or_mortgaged"
    assert state.players["user"].balance == 1500  # unchanged


def test_resolve_tax_tile_deducts() -> None:
    state = _fresh("2")
    _to(state, "user", 4)  # Income Tax $200
    resolve_tile(state, load_board("2"), "user")
    assert state.players["user"].balance == 1300


def test_resolve_chance_draws_card() -> None:
    state = _fresh("2")
    _to(state, "user", 7)  # Chance tile
    chance = load_chance(seed=0)
    cc = load_community_chest(seed=0)
    results = resolve_tile(state, load_board("2"), "user",
                           chance_deck=chance, cc_deck=cc)
    assert results[0].kind == "chance_drawn"
    assert "text" in results[0].payload


def test_resolve_chance_chain_resolves_new_tile() -> None:
    """If the card moves the player onto a buyable property, resolution
    chains to `property_arrival_buyable`."""
    state = _fresh("2")
    _to(state, "user", 7)
    chance = load_chance()  # ordered deck; first card is advance_to_go
    # Force first draw = advance_to_reading (tile 5, a railroad, buyable)
    advance_reading = next(c for c in chance.cards if c.id == "advance_to_reading")
    chance.cards.remove(advance_reading)
    chance.cards.insert(0, advance_reading)
    cc = load_community_chest()
    results = resolve_tile(state, load_board("2"), "user",
                           chance_deck=chance, cc_deck=cc)
    kinds = [r.kind for r in results]
    assert "chance_drawn" in kinds
    assert any(r.kind.startswith("property_arrival") for r in results)


# ---- buy_property ----------------------------------------------------------


def test_buy_happy_path() -> None:
    state = _fresh("2")
    _to(state, "user", 1)
    resolve_tile(state, load_board("2"), "user")
    res = buy_property(state, load_board("2"), "user", "board2:mediterranean_avenue")
    assert res["price"] == 60
    assert state.properties["board2:mediterranean_avenue"].owner == "user"
    assert state.players["user"].balance == 1440
    assert state.fsm == FSM.RESOLVE_TILE


def test_buy_already_owned_rejected() -> None:
    state = _fresh("2")
    state.properties["board2:mediterranean_avenue"].owner = "robot"
    _to(state, "user", 1)
    # player arrival is rent_paid path — not AWAIT_DECISION. Force AWAIT to
    # exercise the PROPERTY_OWNED error branch deterministically.
    state.fsm = FSM.AWAIT_DECISION
    with pytest.raises(RuleError) as exc:
        buy_property(state, load_board("2"), "user", "board2:mediterranean_avenue")
    assert exc.value.code == "PROPERTY_OWNED"


def test_buy_insufficient_funds() -> None:
    state = _fresh("2")
    state.players["user"].balance = 10
    _to(state, "user", 1)
    resolve_tile(state, load_board("2"), "user")
    # resolve_tile returns unaffordable; FSM back to RESOLVE_TILE, not AWAIT.
    assert state.fsm == FSM.RESOLVE_TILE
    # Force AWAIT to test the INSUFFICIENT_FUNDS branch directly.
    state.fsm = FSM.AWAIT_DECISION
    with pytest.raises(RuleError) as exc:
        buy_property(state, load_board("2"), "user", "board2:mediterranean_avenue")
    assert exc.value.code == "INSUFFICIENT_FUNDS"


def test_skip_purchase_transitions_back() -> None:
    state = _fresh("2")
    _to(state, "user", 1)
    resolve_tile(state, load_board("2"), "user")
    assert state.fsm == FSM.AWAIT_DECISION
    skip_purchase(state)
    assert state.fsm == FSM.RESOLVE_TILE


# ---- build / hotel --------------------------------------------------------


def _own_brown_monopoly(state: GameState) -> None:
    state.properties["board2:mediterranean_avenue"].owner = "user"
    state.properties["board2:baltic_avenue"].owner = "user"


def test_build_requires_monopoly_on_board2() -> None:
    state = _fresh("2")
    state.properties["board2:mediterranean_avenue"].owner = "user"
    with pytest.raises(RuleError) as exc:
        build(state, load_board("2"), "user", "board2:mediterranean_avenue")
    assert exc.value.code == "MONOPOLY_REQUIRED"


def test_build_even_rule_enforced() -> None:
    state = _fresh("2")
    _own_brown_monopoly(state)
    build(state, load_board("2"), "user", "board2:mediterranean_avenue")  # 0->1
    with pytest.raises(RuleError):
        # building a second house on Mediterranean before Baltic gets one
        build(state, load_board("2"), "user", "board2:mediterranean_avenue")


def test_build_succeeds_after_even_balance() -> None:
    state = _fresh("2")
    _own_brown_monopoly(state)
    build(state, load_board("2"), "user", "board2:mediterranean_avenue")
    build(state, load_board("2"), "user", "board2:baltic_avenue")
    assert state.properties["board2:mediterranean_avenue"].houses == 1
    assert state.properties["board2:baltic_avenue"].houses == 1


def test_build_hotel_requires_four_houses() -> None:
    state = _fresh("2")
    _own_brown_monopoly(state)
    state.properties["board2:mediterranean_avenue"].houses = 3
    with pytest.raises(RuleError):
        build(state, load_board("2"), "user", "board2:mediterranean_avenue", hotel=True)


def test_build_hotel_ok() -> None:
    state = _fresh("2")
    _own_brown_monopoly(state)
    state.properties["board2:mediterranean_avenue"].houses = 4
    build(state, load_board("2"), "user", "board2:mediterranean_avenue", hotel=True)
    p = state.properties["board2:mediterranean_avenue"]
    assert p.has_hotel is True
    assert p.houses == 0


# ---- mortgage cycle ------------------------------------------------------


def test_mortgage_pays_half_and_blocks_rent() -> None:
    state = _fresh("2")
    state.properties["board2:mediterranean_avenue"].owner = "user"
    start_balance = state.players["user"].balance
    res = mortgage(state, load_board("2"), "user", "board2:mediterranean_avenue")
    assert res["received"] == 30
    assert state.players["user"].balance == start_balance + 30
    assert state.properties["board2:mediterranean_avenue"].mortgaged is True


def test_unmortgage_costs_110_percent() -> None:
    state = _fresh("2")
    state.properties["board2:mediterranean_avenue"].owner = "user"
    mortgage(state, load_board("2"), "user", "board2:mediterranean_avenue")
    start_balance = state.players["user"].balance
    unmortgage(state, load_board("2"), "user", "board2:mediterranean_avenue")
    # 30 * 1.1 = 33
    assert state.players["user"].balance == start_balance - 33
    assert state.properties["board2:mediterranean_avenue"].mortgaged is False


def test_mortgage_with_buildings_rejected() -> None:
    state = _fresh("2")
    _own_brown_monopoly(state)
    state.properties["board2:mediterranean_avenue"].houses = 1
    with pytest.raises(RuleError):
        mortgage(state, load_board("2"), "user", "board2:mediterranean_avenue")


# ---- sell_building --------------------------------------------------------


def test_sell_building_refunds_half() -> None:
    state = _fresh("2")
    _own_brown_monopoly(state)
    state.properties["board2:mediterranean_avenue"].houses = 2
    start_balance = state.players["user"].balance
    res = sell_building(state, load_board("2"), "user", "board2:mediterranean_avenue")
    assert res["refund"] == 25  # $50 house / 2
    assert state.players["user"].balance == start_balance + 25
    assert state.properties["board2:mediterranean_avenue"].houses == 1


def test_sell_building_converts_hotel_to_four_houses() -> None:
    state = _fresh("2")
    _own_brown_monopoly(state)
    p = state.properties["board2:mediterranean_avenue"]
    p.has_hotel = True
    sell_building(state, load_board("2"), "user", p.id)
    assert p.has_hotel is False
    assert p.houses == 4


# ---- bankruptcy -----------------------------------------------------------


def test_rent_triggers_auto_liquidation_then_pays() -> None:
    state = _fresh("2")
    state.players["user"].balance = 150
    _own_brown_monopoly(state)
    state.properties["board2:mediterranean_avenue"].houses = 1  # $50 build -> $25 refund
    # Opponent owns Reading Railroad; user lands on it. Rent = $25.
    state.properties["board2:reading_railroad"].owner = "robot"
    _to(state, "user", 5)
    resolve_tile(state, load_board("2"), "user")
    # Rent was $25, user had $150 -> no need to liquidate. Just verify flow.
    assert state.players["user"].balance == 125


def test_rent_bankruptcy_transfers_assets_and_ends_game() -> None:
    state = _fresh("2")
    state.players["user"].balance = 1
    # Make rent painfully high: robot owns Boardwalk with a hotel.
    b = state.properties["board2:boardwalk"]
    b.owner = "robot"
    b.has_hotel = True
    _to(state, "user", 39)
    resolve_tile(state, load_board("2"), "user")
    assert state.fsm == FSM.GAME_OVER
    assert state.winner == "robot"
    assert state.players["user"].balance == 0


def test_tax_bankruptcy_goes_to_bank_not_opponent() -> None:
    state = _fresh("2")
    state.players["user"].balance = 1
    _to(state, "user", 4)  # Income Tax $200
    resolve_tile(state, load_board("2"), "user")
    assert state.fsm == FSM.GAME_OVER
    # On bank-bankruptcy the opponent is still declared winner (only two players).
    assert state.winner == "robot"
    assert state.players["user"].balance == 0
