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
    even_build_ok,
    is_monopoly,
    initial_properties,
    property_id,
    render_card,
)
from game.state import FSM, GameState, Player, PlayerState


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


# ---- transitions -----------------------------------------------------------


def start_game(state: GameState, board_id: str) -> Board:
    if state.fsm not in (FSM.IDLE, FSM.GAME_OVER):
        raise RuleError("INVALID_STATE", f"cannot start while fsm={state.fsm.value}")
    if board_id not in ("1", "2", "3"):
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


def submit_dice(state: GameState, value: int | tuple[int, int]) -> None:
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
    state.fsm = FSM.MOVING


@dataclass
class MoveResult:
    player: Player
    from_tile: int
    to_tile: int
    dice_sum: int
    wrapped: bool          # crossed the START tile
    lap_completed: bool    # this lap is the player's first lap (Board 3 win)
    winner: Player | None  # set if the move ended the game


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
    if wrapped:
        state.lap_count[player] = state.lap_count.get(player, 0) + 1
        # Board 3 rule: first to complete a full lap wins.
        if board.board_id == "3":
            lap_completed = True
            winner = player
            state.winner = player
            state.fsm = FSM.GAME_OVER

    return MoveResult(
        player=player,
        from_tile=from_tile,
        to_tile=to_tile,
        dice_sum=dice,
        wrapped=wrapped,
        lap_completed=lap_completed,
        winner=winner,
    )


def end_turn(state: GameState) -> None:
    if state.fsm == FSM.GAME_OVER:
        return
    if state.fsm not in (FSM.RESOLVE_TILE, FSM.END_TURN):
        raise RuleError("INVALID_STATE", f"cannot end turn in fsm={state.fsm.value}")
    state.turn = state.other(state.turn)
    state.turn_number += 1
    state.last_dice = None
    state.last_dice_sum = None
    state.pending_dice = None
    state.fsm = FSM.TURN_START


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
            if state.players[player].balance >= (tile.price_buy or 0):
                state.fsm = FSM.AWAIT_DECISION
                return TileResolution(
                    "property_arrival_buyable",
                    tile_index,
                    payload={"property_id": pid, "card": render_card(tile, p, board.board_id)},
                    needs_decision=True,
                )
            return TileResolution(
                "property_arrival_unaffordable",
                tile_index,
                payload={"property_id": pid, "card": render_card(tile, p, board.board_id)},
            )
        if p.owner == player or p.mortgaged:
            return TileResolution("property_arrival_self_or_mortgaged", tile_index,
                                  payload={"property_id": pid})
        rent = props_mod.compute_rent(state, board, tile_index, state.last_dice_sum)
        bankrupt = _pay_rent_or_bankrupt(state, board, player, p.owner, rent)
        return TileResolution(
            "rent_paid" if not bankrupt else "rent_bankruptcy",
            tile_index,
            payload={"property_id": pid, "amount": rent, "payee": p.owner},
            bankrupt_player=player if bankrupt else None,
        )

    if tile.kind == "tax":
        amount = int(tile.amount or 0)
        bankrupt = _pay_bank_or_bankrupt(state, board, player, amount)
        return TileResolution(
            "tax_paid" if not bankrupt else "tax_bankruptcy",
            tile_index,
            payload={"amount": amount},
            bankrupt_player=player if bankrupt else None,
        )

    if tile.kind == "chance" and chance_deck is not None:
        card = chance_deck.draw()
        apply_res = apply_effect(state, board, player, card.effect)
        payload = {"card_id": card.id, "text": card.text, "effect": apply_res}
        if card.effect.get("type") == "grant_jail_free_card":
            # Player keeps the card — don't rotate to bottom.
            pass
        else:
            chance_deck.return_to_bottom(card)
        if apply_res.get("kind") in ("move_to_tile", "move_to_nearest", "move_relative", "go_to_jail"):
            payload["moved_to"] = state.positions[player]
        return TileResolution("chance_drawn", tile_index, payload=payload)

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
    tile = board.tiles[p.tile_index]
    price = tile.price_buy or 0
    if state.players[player].balance < price:
        raise RuleError(
            "INSUFFICIENT_FUNDS", f"balance {state.players[player].balance} < {price}",
            {"balance": state.players[player].balance, "required": price},
        )
    state.players[player].balance -= price
    p.owner = player
    state.fsm = FSM.RESOLVE_TILE
    return {"property_id": pid, "price": price, "owner": player,
            "balance": state.players[player].balance}


def skip_purchase(state: GameState) -> None:
    if state.fsm != FSM.AWAIT_DECISION:
        raise RuleError("INVALID_STATE", f"cannot skip in fsm={state.fsm.value}")
    state.fsm = FSM.RESOLVE_TILE


def build(
    state: GameState, board: Board, player: Player, pid: str,
    *, houses: int = 1, hotel: bool = False,
) -> dict[str, Any]:
    if pid not in state.properties:
        raise RuleError("NOT_FOUND", f"unknown property {pid!r}")
    p = state.properties[pid]
    if p.owner != player:
        raise RuleError("NOT_OWNER", f"{pid} is owned by {p.owner}, not {player}")
    tile = board.tiles[p.tile_index]
    if tile.kind != "property":
        raise RuleError("BAD_REQUEST", f"cannot build on {tile.kind} tile")
    if p.mortgaged:
        raise RuleError("BAD_REQUEST", "cannot build on mortgaged property")

    if hotel:
        if p.houses != 4:
            raise RuleError("BAD_REQUEST", "hotel requires 4 houses first")
        if board.monopoly_bonus_multiplier > 1 and not is_monopoly(
            state, board, tile.color_group or "", player
        ):
            raise RuleError("MONOPOLY_REQUIRED", "hotel requires monopoly")
        cost = tile.price_building or 0
        if state.players[player].balance < cost:
            raise RuleError("INSUFFICIENT_FUNDS", "balance below hotel cost")
        state.players[player].balance -= cost
        p.houses = 0
        p.has_hotel = True
        return {"property_id": pid, "built": "hotel", "cost": cost,
                "balance": state.players[player].balance}

    # houses
    if houses <= 0:
        raise RuleError("BAD_REQUEST", "houses must be positive")
    if p.has_hotel:
        raise RuleError("BAD_REQUEST", "already has hotel")
    if p.houses + houses > 4:
        raise RuleError("BAD_REQUEST", "cannot exceed 4 houses (build a hotel instead)")
    if board.monopoly_bonus_multiplier > 1 and not is_monopoly(
        state, board, tile.color_group or "", player
    ):
        raise RuleError("MONOPOLY_REQUIRED", "building requires monopoly")
    if board.monopoly_bonus_multiplier > 1 and not even_build_ok(
        state, board, tile.color_group or "", pid, houses,
    ):
        raise RuleError("BAD_REQUEST", "even-build rule violated (±1 houses per group)")
    cost = (tile.price_building or 0) * houses
    if state.players[player].balance < cost:
        raise RuleError("INSUFFICIENT_FUNDS", "balance below build cost")
    state.players[player].balance -= cost
    p.houses += houses
    return {"property_id": pid, "built": "house", "houses_added": houses,
            "total_houses": p.houses, "cost": cost,
            "balance": state.players[player].balance}


def sell_building(state: GameState, board: Board, player: Player, pid: str) -> dict[str, Any]:
    p = state.properties[pid]
    if p.owner != player:
        raise RuleError("NOT_OWNER", f"{pid} is owned by {p.owner}")
    tile = board.tiles[p.tile_index]
    price_building = tile.price_building or 0
    refund = price_building // 2
    if p.has_hotel:
        p.has_hotel = False
        p.houses = 4
    elif p.houses > 0:
        p.houses -= 1
    else:
        raise RuleError("BAD_REQUEST", "no buildings to sell")
    state.players[player].balance += refund
    return {"property_id": pid, "refund": refund, "houses": p.houses, "has_hotel": p.has_hotel,
            "balance": state.players[player].balance}


def mortgage(state: GameState, board: Board, player: Player, pid: str) -> dict[str, Any]:
    p = state.properties[pid]
    if p.owner != player:
        raise RuleError("NOT_OWNER", f"{pid} is owned by {p.owner}")
    if p.mortgaged:
        raise RuleError("BAD_REQUEST", "already mortgaged")
    if p.houses > 0 or p.has_hotel:
        raise RuleError("BAD_REQUEST", "sell buildings before mortgaging")
    tile = board.tiles[p.tile_index]
    price_buy = tile.price_buy or 0
    cash = price_buy // 2
    p.mortgaged = True
    state.players[player].balance += cash
    return {"property_id": pid, "received": cash, "balance": state.players[player].balance}


def unmortgage(state: GameState, board: Board, player: Player, pid: str) -> dict[str, Any]:
    p = state.properties[pid]
    if p.owner != player:
        raise RuleError("NOT_OWNER", f"{pid} is owned by {p.owner}")
    if not p.mortgaged:
        raise RuleError("BAD_REQUEST", "not mortgaged")
    tile = board.tiles[p.tile_index]
    price_buy = tile.price_buy or 0
    cost = int((price_buy // 2) * 1.1)
    if state.players[player].balance < cost:
        raise RuleError("INSUFFICIENT_FUNDS", "balance below unmortgage cost")
    state.players[player].balance -= cost
    p.mortgaged = False
    return {"property_id": pid, "paid": cost, "balance": state.players[player].balance}


# ---- bankruptcy ------------------------------------------------------------


def _pay_rent_or_bankrupt(
    state: GameState, board: Board, payer: Player, payee: Player, amount: int,
) -> bool:
    """Attempt to pay `amount` in rent. Auto-liquidates when short. Returns
    True on bankruptcy (assets go to payee, fsm -> GAME_OVER)."""
    if amount <= 0:
        return False
    _auto_liquidate(state, board, payer, amount)
    if state.players[payer].balance >= amount:
        state.players[payer].balance -= amount
        state.players[payee].balance += amount
        return False
    # fully bankrupt — transfer everything remaining to payee
    state.players[payee].balance += state.players[payer].balance
    state.players[payer].balance = 0
    for p in state.properties.values():
        if p.owner == payer:
            p.owner = payee
            # keep buildings/mortgage flags as-is
    state.winner = payee
    state.fsm = FSM.GAME_OVER
    return True


def _pay_bank_or_bankrupt(
    state: GameState, board: Board, payer: Player, amount: int,
) -> bool:
    if amount <= 0:
        return False
    _auto_liquidate(state, board, payer, amount)
    if state.players[payer].balance >= amount:
        state.players[payer].balance -= amount
        return False
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
    return True


def _auto_liquidate(
    state: GameState, board: Board, player: Player, target: int,
) -> None:
    """Sell buildings then mortgage properties until balance >= target or
    nothing left to sell (PRD §7.3.10 order)."""
    # 1. Sell buildings (highest-value first).
    for p in sorted(
        state.properties.values(),
        key=lambda pp: board.tiles[pp.tile_index].price_building or 0,
        reverse=True,
    ):
        if p.owner != player:
            continue
        while state.players[player].balance < target and (p.houses > 0 or p.has_hotel):
            sell_building(state, board, player, p.id)
        if state.players[player].balance >= target:
            return
    # 2. Mortgage remaining properties.
    for p in list(state.properties.values()):
        if p.owner != player or p.mortgaged or p.houses > 0 or p.has_hotel:
            continue
        if state.players[player].balance >= target:
            return
        mortgage(state, board, player, p.id)
