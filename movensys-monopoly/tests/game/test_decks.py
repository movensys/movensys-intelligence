"""Chance / Community Chest deck + effect dispatcher tests (PRD §7.3.6)."""

from __future__ import annotations

import pytest

from game.boards import load_board
from game.decks import Card, load_chance, load_community_chest
from game.effects import EffectError, apply_effect
from game.properties import initial_properties, property_id
from game.state import GameState, PlayerState


# ---- deck loading ---------------------------------------------------------


def test_chance_deck_has_16_cards() -> None:
    deck = load_chance()
    assert len(deck) == 16


def test_community_chest_deck_has_16_cards() -> None:
    deck = load_community_chest()
    assert len(deck) == 16


def test_draw_removes_from_top_and_return_puts_at_bottom() -> None:
    deck = load_chance()
    first = deck.draw()
    assert len(deck) == 15
    deck.return_to_bottom(first)
    assert len(deck) == 16
    # First card should now be at position 15 (bottom)
    ids = [c.id for c in deck.cards]
    assert ids[-1] == first.id


def test_shuffle_is_deterministic_with_seed() -> None:
    a = load_chance(seed=42)
    b = load_chance(seed=42)
    assert [c.id for c in a.cards] == [c.id for c in b.cards]
    c = load_chance(seed=1)
    assert [card.id for card in a.cards] != [card.id for card in c.cards]


def test_card_effect_is_structured() -> None:
    deck = load_chance()
    for card in deck.cards:
        assert "type" in card.effect, f"card {card.id} missing effect.type"


# ---- effects --------------------------------------------------------------


def _state() -> tuple[GameState, "Board"]:  # type: ignore[name-defined]
    board = load_board("2")
    st = GameState(
        board_id="2",
        players={
            "user": PlayerState(id="user", balance=500),
            "robot": PlayerState(id="robot", balance=500),
        },
        positions={"user": 0, "robot": 0},
        properties=initial_properties(board),
    )
    return st, board


def test_collect_adds_to_balance() -> None:
    st, board = _state()
    result = apply_effect(st, board, "user", {"type": "collect", "amount": 150})
    assert st.players["user"].balance == 650
    assert result["amount"] == 150


def test_pay_to_bank() -> None:
    st, board = _state()
    apply_effect(st, board, "user", {"type": "pay", "amount": 50, "to": "bank"})
    assert st.players["user"].balance == 450
    assert st.players["robot"].balance == 500


def test_pay_to_opponent_transfers() -> None:
    st, board = _state()
    apply_effect(st, board, "user", {"type": "pay_each_player", "amount": 50})
    assert st.players["user"].balance == 450
    assert st.players["robot"].balance == 550


def test_collect_from_each_player() -> None:
    st, board = _state()
    apply_effect(st, board, "user", {"type": "collect_from_each_player", "amount": 10})
    assert st.players["user"].balance == 510
    assert st.players["robot"].balance == 490


def test_pay_per_building_counts_houses_and_hotels() -> None:
    st, board = _state()
    st.properties["board2:mediterranean_avenue"].owner = "user"
    st.properties["board2:mediterranean_avenue"].houses = 2
    st.properties["board2:baltic_avenue"].owner = "user"
    st.properties["board2:baltic_avenue"].has_hotel = True
    result = apply_effect(
        st, board, "user",
        {"type": "pay_per_building", "per_house": 25, "per_hotel": 100},
    )
    # 2 houses * 25 + 1 hotel * 100 = 150
    assert result["amount"] == 150
    assert st.players["user"].balance == 350


def test_move_to_tile_advances_and_collects_start_bonus() -> None:
    st, board = _state()
    st.positions["user"] = 36
    # Advance to GO (tile 0), collect on pass
    result = apply_effect(
        st, board, "user",
        {"type": "move_to_tile", "tile_index": 0, "collect_on_pass": True},
    )
    assert st.positions["user"] == 0
    assert result["passed_start"] is True
    assert result["collected"] == board.start_bonus  # 200
    assert st.players["user"].balance == 700


def test_move_to_tile_no_start_bonus_when_not_passed() -> None:
    st, board = _state()
    st.positions["user"] = 5
    result = apply_effect(
        st, board, "user",
        {"type": "move_to_tile", "tile_index": 24, "collect_on_pass": True},
    )
    assert st.positions["user"] == 24
    assert result["passed_start"] is False
    assert result["collected"] == 0
    assert st.players["user"].balance == 500


def test_move_relative_wraps_modulo() -> None:
    st, board = _state()
    st.positions["user"] = 2
    apply_effect(st, board, "user", {"type": "move_relative", "delta": -3})
    # (2 - 3) mod 40 = 39
    assert st.positions["user"] == 39


def test_move_to_nearest_railroad_from_chance() -> None:
    st, board = _state()
    st.positions["user"] = 7  # Chance tile between Oriental and Vermont
    result = apply_effect(
        st, board, "user",
        {"type": "move_to_nearest", "kind": "railroad"},
    )
    # Nearest railroad forward from 7 is Pennsylvania (15)
    assert st.positions["user"] == 15
    assert result["target_kind"] == "railroad"


def test_grant_jail_free_card_sets_flag() -> None:
    st, board = _state()
    apply_effect(st, board, "user", {"type": "grant_jail_free_card"})
    assert st.players["user"].has_jail_free_card is True


def test_go_to_jail_moves_to_jail_visit_and_flags_in_jail() -> None:
    st, board = _state()
    st.positions["user"] = 25
    apply_effect(st, board, "user", {"type": "go_to_jail"})
    # Board 2 jail_visit tile is index 10
    assert st.positions["user"] == 10
    assert st.players["user"].in_jail is True
    assert st.players["user"].jail_turns_left == 3


def test_unknown_effect_raises() -> None:
    st, board = _state()
    with pytest.raises(EffectError):
        apply_effect(st, board, "user", {"type": "teleport_to_mars"})


def test_missing_required_field_raises_bad_request() -> None:
    st, board = _state()
    with pytest.raises(EffectError) as exc:
        apply_effect(st, board, "user", {"type": "collect"})  # no amount
    assert exc.value.code == "BAD_REQUEST"
    assert "amount" in str(exc.value)


def test_malformed_arg_raises_bad_request() -> None:
    st, board = _state()
    with pytest.raises(EffectError) as exc:
        apply_effect(st, board, "user", {"type": "collect", "amount": "not-a-number"})
    assert exc.value.code == "BAD_REQUEST"


# ---- sanity: every card's effect dispatches ------------------------------


@pytest.mark.parametrize("deck_loader", [load_chance, load_community_chest])
def test_every_card_effect_type_is_known(deck_loader) -> None:
    known = {
        "collect", "pay", "pay_each_player", "collect_from_each_player",
        "pay_per_building", "move_to_tile", "move_relative", "move_to_nearest",
        "grant_jail_free_card", "go_to_jail",
    }
    for card in deck_loader().cards:
        assert card.effect["type"] in known, f"card {card.id} has unsupported effect {card.effect['type']!r}"
