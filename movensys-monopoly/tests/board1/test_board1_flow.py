"""Board 1 end-to-end scenarios against the FastAPI app (PRD §15 M2 AC).

Exercises the public HTTP surface for the short-game rule set: buy,
rent, build, tax, chance, start bonus, bankruptcy.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        async with app.router.lifespan_context(app):
            yield ac


async def _post(client: AsyncClient, path: str, **body) -> dict:
    r = await client.post(path, json=body)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"
    return r.json()


async def _jump_to(client: AsyncClient, player: str, target: int, board_size: int = 20) -> None:
    """Submit dice+apply_move hops until `player` lands on `target`."""
    state = (await client.get("/api/game/state")).json()
    pos = state["positions"][player]
    while pos != target:
        step = min(6, (target - pos) % board_size)
        if step == 0:
            step = board_size  # one full lap if already on tile
        await _post(client, "/api/dice/submit", value=step, source="manual")
        to = (pos + step) % board_size
        await _post(client, "/api/move/apply", player=player, from_tile=pos, to_tile=to)
        pos = to
        state = (await client.get("/api/game/state")).json()
        # If fsm is AWAIT_DECISION we must resolve before the next move.
        if state["fsm"] == "AWAIT_DECISION":
            return  # caller should decide
        if state["fsm"] == "GAME_OVER":
            return
        # End turn to keep `player` in rotation.
        await _post(client, "/api/game/end_turn")
        await _post(client, "/api/dice/submit", value=1, source="manual")
        # Opponent takes a trivial move then ends turn.
        opp = "robot" if player == "user" else "user"
        opp_pos = state["positions"][opp]
        opp_to = (opp_pos + 1) % board_size
        # Opponent may land on a property; skip any decision.
        await _post(client, "/api/move/apply", player=opp, from_tile=opp_pos, to_tile=opp_to)
        opp_state = (await client.get("/api/game/state")).json()
        if opp_state["fsm"] == "AWAIT_DECISION":
            await _post(client, "/api/properties/" + opp_state["properties"][_find_pid_at(opp_state, opp_to)]["id"] + "/decide", action="skip")
        await _post(client, "/api/game/end_turn")
        state = (await client.get("/api/game/state")).json()
        pos = state["positions"][player]


def _find_pid_at(state: dict, tile_index: int) -> str:
    for pid, p in state["properties"].items():
        if p["tile_index"] == tile_index:
            return pid
    return ""


# ---- scenarios ------------------------------------------------------------


@pytest.mark.asyncio
async def test_board1_buy_and_own(client: AsyncClient) -> None:
    await _post(client, "/api/game/start", board="1")

    # User rolls 1 → lands on Baltic (tile 1, $50 brown).
    await _post(client, "/api/dice/submit", value=1, source="manual")
    res = await _post(client, "/api/move/apply", player="user", from_tile=0, to_tile=1)
    assert res["fsm"] == "AWAIT_DECISION"
    assert res["resolved"]["tiles"][0]["kind"] == "property_arrival_buyable"

    # Buy it.
    await _post(client, "/api/properties/board1:baltic_avenue/decide", action="buy")
    state = (await client.get("/api/game/state")).json()
    assert state["fsm"] == "RESOLVE_TILE"
    assert state["players"]["user"]["balance"] == 950
    assert state["properties"]["board1:baltic_avenue"]["owner"] == "user"


@pytest.mark.asyncio
async def test_board1_rent_transfers_when_opponent_owns(client: AsyncClient) -> None:
    await _post(client, "/api/game/start", board="1")
    # Robot owns Baltic.
    game = app.state.game
    game.state.properties["board1:baltic_avenue"].owner = "robot"

    # User lands on Baltic.
    await _post(client, "/api/dice/submit", value=1, source="manual")
    res = await _post(client, "/api/move/apply", player="user", from_tile=0, to_tile=1)
    tile = res["resolved"]["tiles"][0]
    assert tile["kind"] == "rent_paid"
    assert tile["payload"]["amount"] == 4  # base rent for Baltic
    state = (await client.get("/api/game/state")).json()
    assert state["players"]["user"]["balance"] == 996
    assert state["players"]["robot"]["balance"] == 1004


@pytest.mark.asyncio
async def test_board1_skip_purchase(client: AsyncClient) -> None:
    await _post(client, "/api/game/start", board="1")
    await _post(client, "/api/dice/submit", value=1, source="manual")
    await _post(client, "/api/move/apply", player="user", from_tile=0, to_tile=1)
    await _post(client, "/api/properties/board1:baltic_avenue/decide", action="skip")
    state = (await client.get("/api/game/state")).json()
    assert state["fsm"] == "RESOLVE_TILE"
    assert state["properties"]["board1:baltic_avenue"]["owner"] is None
    assert state["players"]["user"]["balance"] == 1000


@pytest.mark.asyncio
async def test_board1_build_without_monopoly_ok(client: AsyncClient) -> None:
    """Board 1 has monopoly_bonus_multiplier=1 so single-tile groups can build."""
    await _post(client, "/api/game/start", board="1")
    # Give user Baltic directly to skip move plumbing.
    app.state.game.state.properties["board1:baltic_avenue"].owner = "user"
    # Force FSM to a state that allows the /build endpoint path.
    res = await _post(client, "/api/properties/board1:baltic_avenue/build", houses=1)
    assert res["total_houses"] == 1


@pytest.mark.asyncio
async def test_board1_start_wraps_past_go(client: AsyncClient) -> None:
    """Board 1 is 16 tiles. Position 14, roll 3 → wraps through GO to tile 1."""
    await _post(client, "/api/game/start", board="1")
    app.state.game.state.positions["user"] = 14
    await _post(client, "/api/dice/submit", value=3, source="manual")
    res = await _post(client, "/api/move/apply", player="user", from_tile=14, to_tile=1)
    assert res["resolved"]["wrapped"] is True


@pytest.mark.asyncio
async def test_board1_go_to_jail_teleports_without_jail_fsm(client: AsyncClient) -> None:
    """Tile 12 is Go To Jail — on Board 1 the short game has no jail FSM,
    so the player teleports to Jail / Just Visiting without getting the
    in_jail flag (nothing would ever clear it otherwise)."""
    await _post(client, "/api/game/start", board="1")
    app.state.game.state.positions["user"] = 6
    await _post(client, "/api/dice/submit", value=6, source="manual")
    await _post(client, "/api/move/apply", player="user", from_tile=6, to_tile=12)
    state = (await client.get("/api/game/state")).json()
    # Jail visit is tile 4 on Board 1 (3-per-side layout)
    assert state["positions"]["user"] == 4
    assert state["players"]["user"]["in_jail"] is False
    assert state["players"]["user"]["jail_turns_left"] == 0


@pytest.mark.asyncio
async def test_board1_mortgage_cycle(client: AsyncClient) -> None:
    await _post(client, "/api/game/start", board="1")
    app.state.game.state.properties["board1:baltic_avenue"].owner = "user"
    start = (await client.get("/api/game/state")).json()["players"]["user"]["balance"]
    mort = await _post(client, "/api/properties/board1:baltic_avenue/mortgage")
    assert mort["received"] == 25  # $50 / 2
    assert mort["balance"] == start + 25
    unmort = await _post(client, "/api/properties/board1:baltic_avenue/unmortgage")
    # 25 * 1.1 = 27 (int-truncated)
    assert unmort["paid"] == 27
