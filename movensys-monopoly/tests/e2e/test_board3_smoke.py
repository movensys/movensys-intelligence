"""End-to-end Board 3 smoke test (PRD §14, §13, §15 M1 AC).

Runs the real FastAPI app against an in-process ASGI transport — no
network, no external services. Proves the minimum pipeline:

    start(board=3) -> submit_dice -> apply_move -> ... -> winner non-null

Exercised purely through the public HTTP surface so this doubles as a
regression guard for the API contract.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # Trigger lifespan startup/shutdown via the context.
        async with app.router.lifespan_context(app):
            yield ac


async def _post(client: AsyncClient, path: str, **body):
    resp = await client.post(path, json=body)
    assert resp.status_code == 200, f"{path} -> {resp.status_code} {resp.text}"
    return resp.json()


@pytest.mark.asyncio
async def test_board3_full_lap_to_winner(client: AsyncClient) -> None:
    # 1. No winner before the game starts.
    winner = (await client.get("/api/game/winner")).json()
    assert winner == {"winner": None}

    # 2. Start Board 3.
    started = await _post(client, "/api/game/start", board="3")
    assert started == {"fsm": "TURN_START", "turn": "user"}

    board_size = 12
    positions = {"user": 0, "robot": 0}
    moves = 0

    # 3. Alternate turns with a deterministic dice of 3 per turn. After 4
    # user moves (12 tiles) the user wraps back to START and wins.
    while True:
        state = (await client.get("/api/game/state")).json()
        turn = state["turn"]
        await _post(client, "/api/dice/submit", value=3, source="manual")
        pos = positions[turn]
        expected_to = (pos + 3) % board_size
        result = await _post(
            client,
            "/api/move/apply",
            player=turn,
            from_tile=pos,
            to_tile=expected_to,
        )
        moves += 1
        positions[turn] = expected_to
        if result["resolved"]["winner"]:
            assert result["resolved"]["winner"] == "user"
            break
        # End this turn to hand off to the other player.
        await _post(client, "/api/game/end_turn")
        assert moves < 40, "a 12-tile lap should close well before 40 moves"

    # 4. /api/game/winner reports the same winner.
    winner = (await client.get("/api/game/winner")).json()
    assert winner == {"winner": "user"}

    # 5. FSM is terminal.
    state = (await client.get("/api/game/state")).json()
    assert state["fsm"] == "GAME_OVER"
    assert state["winner"] == "user"


@pytest.mark.asyncio
async def test_tile_mismatch_returns_envelope(client: AsyncClient) -> None:
    await _post(client, "/api/game/start", board="3")
    await _post(client, "/api/dice/submit", value=4, source="manual")
    resp = await client.post(
        "/api/move/apply",
        json={"player": "user", "from_tile": 0, "to_tile": 9},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "TILE_MISMATCH"
    assert body["detail"]["details"]["expected_to"] == 4


@pytest.mark.asyncio
async def test_stub_mode_adapter_health(client: AsyncClient) -> None:
    """Covers the CI invariant from PRD §14."""
    resp = await client.get("/api/robot/health")
    assert resp.status_code == 200
    assert resp.json() == {"mode": "stub"}


@pytest.mark.asyncio
async def test_modes_aggregate_snapshot(client: AsyncClient) -> None:
    """The UI boots with a single /api/modes call instead of polling four
    endpoints on an interval. Contract: one snapshot with all four keys,
    each entry at least carries the same shape its /*/health twin does
    so the same modeBadge() renderer can consume either."""
    resp = await client.get("/api/modes")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"stt", "llm", "robot", "ros2"}
    # Adapters report {"mode": ...} in stub mode.
    assert body["stt"]["mode"] == "stub"
    assert body["llm"]["mode"] == "stub"
    assert body["robot"]["mode"] == "stub"
    # ROS 2 bridge carries a different shape.
    assert set(body["ros2"]) == {"enabled", "cameras_enabled"}
