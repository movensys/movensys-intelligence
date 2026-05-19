"""Game rule engine (PRD §7).

Pure functions only — no async, no network, no globals. GameManager
wraps them with a lock and pub/sub.

- start_game / submit_dice / apply_move / end_turn  (M1)
- resolve_tile                                      (M2) routing by tile kind
- buy_property / build / mortgage / unmortgage / sell_building  (M2)
- resolve_bankruptcy                                (M2) liquidate then GAME_OVER
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from game import properties as props_mod
from game.boards import Board, load_board
from game.decks import Deck
from game.effects import apply_effect
from game.properties import (
    initial_properties,
    property_id,
    render_card,
)
from game.state import FSM, GameState, Player, PlayerState


# Game-wide flat economy (spec §2, §4.x).
TIER_PRICE = 100          # cost per tier crossed (and refund on sell)
LAND_PRICE = 1 * TIER_PRICE   # tier 1 → $100 cumulative
HOUSE_PRICE = 2 * TIER_PRICE  # tier 2 → $200 cumulative
HOTEL_PRICE = 3 * TIER_PRICE  # tier 3 → $300 cumulative
TAX_AMOUNT = 100          # flat tax for Non-Free Parking (§4.3)
CHANCE_AMOUNT = 200       # chance card payout magnitude (§4.4)
LAPS_TO_WIN = 5           # end-of-game lap-count cap (§6.2)


def tier_of(p) -> int:
    """1 = land, 2 = house, 3 = hotel, 0 = unowned."""
    if p.owner is None:
        return 0
    if p.has_hotel:
        return 3
    if p.houses > 0:
        return 2
    return 1


def _set_tier(p, target: int) -> None:
    """Mutate p so its tier becomes `target` (1/2/3). Owner must already be set."""
    if target <= 0:
        p.owner = None
        p.houses = 0
        p.has_hotel = False
        p.mortgaged = False
        return
    p.has_hotel = target == 3
    p.houses = 1 if target == 2 else 0
    p.mortgaged = False


def assets_value(state: GameState, player: Player) -> int:
    """Sum of tier × $100 over all properties owned by `player` (spec §2.1.2)."""
    return sum(
        tier_of(p) * TIER_PRICE for p in state.properties.values() if p.owner == player
    )


def total_money(state: GameState, player: Player) -> int:
    """Liquid + assets (spec §6.2.1)."""
    return state.players[player].balance + assets_value(state, player)


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


def _tile_pid(board: Board, tile_index: int) -> str:
    return property_id(board.board_id, board.tiles[tile_index].name)


def _max_tier(tile) -> int:
    """Max owned tier for a tile kind (spec §4.1, §4.2)."""
    return 3 if tile.kind == "property" else 1


# ---- transitions -----------------------------------------------------------


def start_game(state: GameState, board_id: str) -> Board:
    # Singleton-game model: pressing "Start" always begins a fresh game
    # even mid-play. The reset below clobbers every in-memory field, so
    # there's nothing to protect from a second /game/start call.
    if board_id != "final":
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
    state.properties.clear()
    _init_players(state, board)
    state.properties.update(initial_properties(board))
    return board


def submit_dice(state: GameState, value: int | tuple[int, int]) -> dict[str, Any] | None:
    """Submit a dice roll. Spec §4.5 jail handling:
      - if not jailed: normal flow (FSM → MOVING)
      - if jailed and the rolled face is 6: escape, normal move
      - if jailed and turns_left > 0: decrement, **skip the move** by
        going straight to RESOLVE_TILE (the manager runs no resolution
        for a jail-skipped turn and end_turn is the next action)
      - if jailed and turns_left == 0: auto-release, normal flow
    Returns a payload describing the jail outcome, or None if no jail
    transition happened.
    """
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

    player = state.turn
    p_state = state.players.get(player)
    jail_payload: dict[str, Any] | None = None
    if p_state is not None and p_state.in_jail:
        # Single-die move from IN_JAIL — escape iff face is 6 (spec §4.5.2.1).
        face_for_escape = state.last_dice[0]
        if face_for_escape == 6:
            p_state.in_jail = False
            p_state.jail_turns_left = 0
            jail_payload = {"kind": "jail_escaped", "player": player}
        elif p_state.jail_turns_left > 0:
            p_state.jail_turns_left -= 1
            state.pending_dice = None
            state.fsm = FSM.END_TURN
            jail_payload = {
                "kind": "jail_skipped",
                "player": player,
                "turns_left": p_state.jail_turns_left,
            }
            return jail_payload
        else:
            p_state.in_jail = False
            jail_payload = {"kind": "jail_released", "player": player}
    state.fsm = FSM.MOVING
    return jail_payload


@dataclass
class MoveResult:
    player: Player
    from_tile: int
    to_tile: int
    dice_sum: int
    wrapped: bool                # crossed the START tile
    lap_completed: bool          # this lap is the player's first lap (Board 3 win)
    winner: Player | None        # set if the move ended the game
    start_bonus_collected: int = 0  # +$100 on Board 1, +$200 on Board 2, etc.


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
    # Landing on the jail_visit tile via dice is "just visiting" — a no_op
    # resolution (see _resolve_once). Only the GO_TO_JAIL teleport sets
    # in_jail.
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
    bonus = 0
    if wrapped:
        state.lap_count[player] = state.lap_count.get(player, 0) + 1
        bonus = board.start_bonus
        if bonus > 0:
            state.players[player].balance += bonus

    return MoveResult(
        player=player,
        from_tile=from_tile,
        to_tile=to_tile,
        dice_sum=dice,
        wrapped=wrapped,
        lap_completed=lap_completed,
        winner=winner,
        start_bonus_collected=bonus,
    )


def end_turn(state: GameState) -> dict[str, Any] | None:
    """Hand control to the other player. Also runs the lap-cap check
    (spec §6.2): if any player has completed `LAPS_TO_WIN` laps, the
    game ends and winner is decided by total_money. Returns the
    end-of-game payload when the game ends, else None.
    """
    if state.fsm == FSM.GAME_OVER:
        return None
    if state.fsm not in (FSM.RESOLVE_TILE, FSM.END_TURN):
        raise RuleError("INVALID_STATE", f"cannot end turn in fsm={state.fsm.value}")
    state.turn = state.other(state.turn)
    state.turn_number += 1
    state.last_dice = None
    state.last_dice_sum = None
    state.pending_dice = None
    state.fsm = FSM.TURN_START

    # Spec §6.2 — lap cap.
    if any(state.lap_count.get(p, 0) >= LAPS_TO_WIN for p in ("user", "robot")):
        totals = {p: total_money(state, p) for p in ("user", "robot")}
        if totals["user"] > totals["robot"]:
            state.winner = "user"
        elif totals["robot"] > totals["user"]:
            state.winner = "robot"
        else:
            state.winner = None  # tie — see "draw" flag in payload
        state.fsm = FSM.GAME_OVER
        return {
            "winner": state.winner,
            "draw": state.winner is None,
            "reason": "lap_cap",
            "totals": totals,
            "lap_count": dict(state.lap_count),
        }
    return None


# ============================================================================
# Tile resolution (M2)
# ============================================================================


@dataclass
class TileResolution:
    kind: str
    tile_index: int
    payload: dict[str, Any] = field(default_factory=dict)
    needs_decision: bool = False
    bankrupt_player: Player | None = None


def resolve_tile(
    state: GameState,
    board: Board,
    player: Player,
    *,
    chance_deck: Deck | None = None,
    cc_deck: Deck | None = None,
    max_chain: int = 3,
) -> list[TileResolution]:
    """Dispatch the player's current tile. May recurse when chance cards
    move them to another tile — up to `max_chain` hops.
    """
    if state.fsm != FSM.RESOLVE_TILE:
        raise RuleError("INVALID_STATE", f"cannot resolve in fsm={state.fsm.value}")

    results: list[TileResolution] = []
    for _ in range(max_chain):
        res = _resolve_once(state, board, player, chance_deck=chance_deck, cc_deck=cc_deck)
        results.append(res)
        if res.needs_decision or res.bankrupt_player is not None:
            break
        # If the resolution kept us on the same tile (non-movement), stop.
        if res.kind not in ("chance_drawn", "community_chest_drawn") or "moved_to" not in res.payload:
            break
        # Otherwise continue resolving the new tile.
    return results


def _resolve_once(
    state: GameState,
    board: Board,
    player: Player,
    *,
    chance_deck: Deck | None,
    cc_deck: Deck | None,
) -> TileResolution:
    tile_index = state.positions[player]
    tile = board.tiles[tile_index]

    if tile.kind == "start":
        return TileResolution("start", tile_index)

    if tile.kind in ("property", "railroad", "utility"):
        pid = _tile_pid(board, tile_index)
        p = state.properties[pid]
        if p.owner is None:
            if state.players[player].balance >= LAND_PRICE:
                state.fsm = FSM.AWAIT_DECISION
                return TileResolution(
                    "property_arrival_buyable",
                    tile_index,
                    payload={"property_id": pid, "card": render_card(tile, p, board.board_id),
                             "current_tier": 0, "max_tier": _max_tier(tile)},
                    needs_decision=True,
                )
            return TileResolution(
                "property_arrival_unaffordable",
                tile_index,
                payload={"property_id": pid, "card": render_card(tile, p, board.board_id)},
            )
        if p.owner == player:
            # Spec §4.1.2: revisiting an already-owned property opens the
            # upgrade modal (unless it's already at max tier for this kind:
            # property → tier 3, utility/railroad → tier 1).
            current = tier_of(p)
            max_tier = _max_tier(tile)
            if current < max_tier:
                state.fsm = FSM.AWAIT_DECISION
                return TileResolution(
                    "property_arrival_buyable",
                    tile_index,
                    payload={"property_id": pid, "card": render_card(tile, p, board.board_id),
                             "current_tier": current, "max_tier": max_tier},
                    needs_decision=True,
                )
            return TileResolution("property_arrival_self_or_mortgaged", tile_index,
                                  payload={"property_id": pid})
        rent = props_mod.compute_rent(state, board, tile_index, state.last_dice_sum)
        bankrupt, liq = _pay_rent_or_bankrupt(state, board, player, p.owner, rent)
        return TileResolution(
            "rent_paid" if not bankrupt else "rent_bankruptcy",
            tile_index,
            payload={"property_id": pid, "amount": rent, "payee": p.owner,
                     "liquidation": liq},
            bankrupt_player=player if bankrupt else None,
        )

    if tile.kind == "tax":
        bankrupt, liq = _pay_bank_or_bankrupt(state, board, player, TAX_AMOUNT)
        return TileResolution(
            "tax_paid" if not bankrupt else "tax_bankruptcy",
            tile_index,
            payload={"amount": TAX_AMOUNT, "liquidation": liq},
            bankrupt_player=player if bankrupt else None,
        )

    if tile.kind == "chance":
        # Spec §4.4: random ±$200 coin flip. Deck is unused.
        import random
        delta = random.choice([+CHANCE_AMOUNT, -CHANCE_AMOUNT])
        if delta > 0:
            state.players[player].balance += delta
            return TileResolution(
                "chance_drawn", tile_index,
                payload={"amount": delta, "direction": "collect",
                         "balance": state.players[player].balance},
            )
        amount = -delta
        bankrupt, liq = _pay_bank_or_bankrupt(state, board, player, amount)
        return TileResolution(
            "chance_drawn" if not bankrupt else "chance_bankruptcy",
            tile_index,
            payload={"amount": -amount, "direction": "pay", "liquidation": liq,
                     "balance": state.players[player].balance},
            bankrupt_player=player if bankrupt else None,
        )

    if tile.kind == "community_chest" and cc_deck is not None:
        card = cc_deck.draw()
        apply_res = apply_effect(state, board, player, card.effect)
        payload = {"card_id": card.id, "text": card.text, "effect": apply_res}
        if card.effect.get("type") != "grant_jail_free_card":
            cc_deck.return_to_bottom(card)
        if apply_res.get("kind") in ("move_to_tile", "move_to_nearest", "move_relative", "go_to_jail"):
            payload["moved_to"] = state.positions[player]
        return TileResolution("community_chest_drawn", tile_index, payload=payload)

    if tile.kind == "go_to_jail":
        apply_res = apply_effect(state, board, player, {"type": "go_to_jail"})
        return TileResolution("go_to_jail", tile_index, payload=apply_res)

    # free_parking, jail_visit, blank
    return TileResolution("no_op", tile_index, payload={"tile_kind": tile.kind})


# ---- property transactions -------------------------------------------------


def buy_property(state: GameState, board: Board, player: Player, pid: str) -> dict[str, Any]:
    if state.fsm != FSM.AWAIT_DECISION:
        raise RuleError("INVALID_STATE", f"cannot buy in fsm={state.fsm.value}")
    if pid not in state.properties:
        raise RuleError("NOT_FOUND", f"unknown property {pid!r}")
    p = state.properties[pid]
    if p.owner is not None:
        raise RuleError("PROPERTY_OWNED", f"{pid} already owned by {p.owner}")
    price = LAND_PRICE  # flat land tier (spec §4.1)
    if state.players[player].balance < price:
        raise RuleError(
            "INSUFFICIENT_FUNDS", f"balance {state.players[player].balance} < {price}",
            {"balance": state.players[player].balance, "required": price},
        )
    state.players[player].balance -= price
    p.owner = player
    p.houses = 0
    p.has_hotel = False
    p.mortgaged = False
    state.fsm = FSM.RESOLVE_TILE
    return {"property_id": pid, "price": price, "owner": player, "tier": 1,
            "balance": state.players[player].balance}


def skip_purchase(state: GameState) -> None:
    if state.fsm != FSM.AWAIT_DECISION:
        raise RuleError("INVALID_STATE", f"cannot skip in fsm={state.fsm.value}")
    state.fsm = FSM.RESOLVE_TILE


def build(
    state: GameState, board: Board, player: Player, pid: str,
    *, houses: int = 1, hotel: bool = False,
) -> dict[str, Any]:
    """Upgrade to a higher tier (spec §4.1.2). Cost = $100 × tiers crossed.

    `hotel=True` targets tier 3, any positive `houses` targets tier 2.
    """
    if pid not in state.properties:
        raise RuleError("NOT_FOUND", f"unknown property {pid!r}")
    p = state.properties[pid]
    if p.owner != player:
        raise RuleError("NOT_OWNER", f"{pid} is owned by {p.owner}, not {player}")
    tile = board.tiles[p.tile_index]
    if tile.kind != "property":
        raise RuleError("BAD_REQUEST", f"cannot build on {tile.kind} tile")

    current = tier_of(p)
    target = 3 if hotel else 2
    if target <= current:
        raise RuleError("BAD_REQUEST", f"already at tier {current}")

    cost = (target - current) * TIER_PRICE
    if state.players[player].balance < cost:
        raise RuleError("INSUFFICIENT_FUNDS", "balance below build cost")
    state.players[player].balance -= cost
    _set_tier(p, target)
    return {"property_id": pid, "tier": target,
            "tier_label": "hotel" if target == 3 else "house",
            "cost": cost,
            "balance": state.players[player].balance}


def sell_tier(state: GameState, board: Board, player: Player, pid: str) -> dict[str, Any]:
    """Drop one tier (hotel→house, house→land, or land→unowned).

    This is the only sell path under the spec — invoked from auto-liquidation,
    never from a voluntary user action. Refund = $100 per tier dropped.
    """
    p = state.properties[pid]
    if p.owner != player:
        raise RuleError("NOT_OWNER", f"{pid} is owned by {p.owner}")
    current = tier_of(p)
    if current <= 0:
        raise RuleError("BAD_REQUEST", "nothing to sell — property is unowned")
    new_tier = current - 1
    _set_tier(p, new_tier)
    state.players[player].balance += TIER_PRICE
    return {"property_id": pid, "refund": TIER_PRICE,
            "from_tier": current, "to_tier": new_tier,
            "balance": state.players[player].balance}


# Back-compat aliases — older code paths (and a few tests) still import these.
# Both collapse to sell_tier under the flat-economy spec.
sell_building = sell_tier
mortgage = sell_tier


def unmortgage(*_args, **_kwargs):  # pragma: no cover — voluntary mortgage is gone
    raise RuleError("BAD_REQUEST", "unmortgage is not part of the spec")


# ---- bankruptcy ------------------------------------------------------------


def _pay_rent_or_bankrupt(
    state: GameState, board: Board, payer: Player, payee: Player, amount: int,
) -> tuple[bool, list[dict[str, Any]]]:
    """Attempt to pay `amount` in rent. Auto-liquidates when short. Returns
    (bankrupt, liquidation_steps). On bankruptcy assets transfer to payee
    and fsm -> GAME_OVER."""
    if amount <= 0:
        return False, []
    steps = _auto_liquidate(state, board, payer, amount)
    if state.players[payer].balance >= amount:
        state.players[payer].balance -= amount
        state.players[payee].balance += amount
        return False, steps
    # fully bankrupt — transfer everything remaining to payee
    state.players[payee].balance += state.players[payer].balance
    state.players[payer].balance = 0
    for p in state.properties.values():
        if p.owner == payer:
            p.owner = payee
            # keep buildings/mortgage flags as-is
    state.winner = payee
    state.fsm = FSM.GAME_OVER
    return True, steps


def _pay_bank_or_bankrupt(
    state: GameState, board: Board, payer: Player, amount: int,
) -> tuple[bool, list[dict[str, Any]]]:
    if amount <= 0:
        return False, []
    steps = _auto_liquidate(state, board, payer, amount)
    if state.players[payer].balance >= amount:
        state.players[payer].balance -= amount
        return False, steps
    # unpaid tax → bankrupt to bank → properties return to bank (no owner)
    state.players[payer].balance = 0
    for p in state.properties.values():
        if p.owner == payer:
            p.owner = None
            p.houses = 0
            p.has_hotel = False
            p.mortgaged = False
    state.winner = state.other(payer)
    state.fsm = FSM.GAME_OVER
    return True, steps


def _auto_liquidate(
    state: GameState, board: Board, player: Player, target: int,
) -> list[dict[str, Any]]:
    """Drop tiers one at a time until balance >= target or nothing left to
    sell (spec §5.2). Order: hotels first, then houses, then lands. Each
    step refunds $100 and emits a single `tier_sold` event.
    """
    steps: list[dict[str, Any]] = []

    def _drop_at_tier(target_tier: int) -> None:
        """Drop one tier on every property currently at exactly `target_tier`."""
        for p in list(state.properties.values()):
            if state.players[player].balance >= target:
                return
            if p.owner != player or tier_of(p) != target_tier:
                continue
            steps.append({"kind": "tier_sold", **sell_tier(state, board, player, p.id)})

    # Hotels (tier 3) → houses
    _drop_at_tier(3)
    if state.players[player].balance >= target:
        return steps
    # Houses (tier 2) → land
    _drop_at_tier(2)
    if state.players[player].balance >= target:
        return steps
    # Land (tier 1) → unowned
    _drop_at_tier(1)
    return steps
