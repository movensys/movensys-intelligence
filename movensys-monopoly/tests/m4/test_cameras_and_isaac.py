"""M4 acceptance — camera WS/REST proxies + Isaac card-spawn hook.

These tests are resilient to both environments:
  - CI / dev laptop: ROS 2 unavailable → bridge disabled, frames empty.
  - ROS host: bridge spins, may or may not have received frames yet.

For deterministic "no data" assertions we force-disable the bridge
inside the test and clear the frame cache, so the behaviour is tested
regardless of host setup.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        async with app.router.lifespan_context(app):
            yield ac


def _force_disable_bridge(application) -> None:
    bridge = application.state.ros2
    bridge._enabled = False
    bridge._cameras_enabled = False
    bridge._frames = {k: None for k in bridge._frames}


@pytest.mark.asyncio
async def test_ros2_health_exposes_camera_and_isaac_fields(client: AsyncClient) -> None:
    resp = await client.get("/api/ros2/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"enabled", "cameras_enabled", "isaac_topic"}
    assert isinstance(body["enabled"], bool)
    assert isinstance(body["cameras_enabled"], bool)
    assert body["isaac_topic"]  # default /isaac/card_spawn or env override


@pytest.mark.asyncio
async def test_topics_rest_returns_503_when_bridge_disabled() -> None:
    with TestClient(app) as tc:
        _force_disable_bridge(app)
        for path in (
            "/api/topics/image_top/rgb",
            "/api/topics/image_top/depth",
            "/api/topics/image_top/camera_info",
            "/api/topics/image_hand/rgb",
            "/api/topics/image_hand/depth",
            "/api/topics/image_hand/camera_info",
        ):
            resp = tc.get(path)
            assert resp.status_code == 503, f"{path} -> {resp.status_code}"
            assert resp.json()["error"]["code"] == "ADAPTER_UNAVAILABLE"


def test_ws_camera_stream_reports_no_data() -> None:
    """WS envelope must be {data, error} even when no frame has arrived —
    the UI relies on that to show the 'No stream' state."""
    with TestClient(app) as tc:
        _force_disable_bridge(app)
        with tc.websocket_connect("/api/stream/image_top/rgb") as ws:
            msg = json.loads(ws.receive_text())
            assert msg == {"data": None, "error": "No data"}
        with tc.websocket_connect("/api/stream/image_hand/camera_info") as ws:
            msg = json.loads(ws.receive_text())
            assert msg == {"data": None, "error": "No data"}


def test_card_spawn_hook_fires_on_chance_draw() -> None:
    """When a Chance card is drawn the Isaac hook must receive
    {deck, card_id, tile_index}. We use TestClient so the lifespan wires
    the default hook, then swap it for a capture list."""
    captured: list[dict] = []
    with TestClient(app) as tc:
        app.state.game.card_spawn_hook = captured.append
        assert tc.post("/api/game/start", json={"board": "2"}).status_code == 200
        tc.post("/api/dice/submit", json={"value": [3, 4], "source": "manual"})
        resp = tc.post(
            "/api/move/apply",
            json={"player": "user", "from_tile": 0, "to_tile": 7},
        )
        assert resp.status_code == 200
        tiles = resp.json()["resolved"]["tiles"]
        assert any(t["kind"] == "chance_drawn" for t in tiles), tiles

    assert len(captured) == 1, captured
    evt = captured[0]
    assert evt["deck"] == "chance"
    assert evt["tile_index"] == 7
    assert isinstance(evt["card_id"], str) and evt["card_id"]


def test_card_spawn_hook_noop_when_unset() -> None:
    with TestClient(app) as tc:
        app.state.game.card_spawn_hook = None
        tc.post("/api/game/start", json={"board": "2"})
        tc.post("/api/dice/submit", json={"value": [3, 4], "source": "manual"})
        resp = tc.post(
            "/api/move/apply",
            json={"player": "user", "from_tile": 0, "to_tile": 7},
        )
        assert resp.status_code == 200


def test_card_spawn_hook_exception_does_not_stall_game() -> None:
    def boom(_payload: dict) -> None:
        raise RuntimeError("simulated isaac transport failure")

    with TestClient(app) as tc:
        app.state.game.card_spawn_hook = boom
        tc.post("/api/game/start", json={"board": "2"})
        tc.post("/api/dice/submit", json={"value": [3, 4], "source": "manual"})
        resp = tc.post(
            "/api/move/apply",
            json={"player": "user", "from_tile": 0, "to_tile": 7},
        )
        assert resp.status_code == 200


def test_community_chest_card_draw_also_fires_hook() -> None:
    """Board 2 tile 2 is Community Chest."""
    captured: list[dict] = []
    with TestClient(app) as tc:
        app.state.game.card_spawn_hook = captured.append
        tc.post("/api/game/start", json={"board": "2"})
        tc.post("/api/dice/submit", json={"value": 2, "source": "manual"})
        resp = tc.post(
            "/api/move/apply",
            json={"player": "user", "from_tile": 0, "to_tile": 2},
        )
        assert resp.status_code == 200

    # A CC card may have moved the player onto a Chance tile too (chain),
    # so allow ≥1 spawn but require at least one community_chest.
    decks = [c["deck"] for c in captured]
    assert "community_chest" in decks, decks
