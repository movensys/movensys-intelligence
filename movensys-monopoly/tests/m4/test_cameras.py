"""Camera WS/REST proxies — work whether ROS 2 is available or not."""

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
async def test_ros2_health_exposes_camera_fields(client: AsyncClient) -> None:
    resp = await client.get("/api/ros2/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"enabled", "cameras_enabled"}
    assert isinstance(body["enabled"], bool)
    assert isinstance(body["cameras_enabled"], bool)


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
            assert resp.json()["detail"]["code"] == "ADAPTER_UNAVAILABLE"


def test_ws_camera_stream_reports_no_data() -> None:
    with TestClient(app) as tc:
        _force_disable_bridge(app)
        with tc.websocket_connect("/api/stream/image_top/rgb") as ws:
            msg = json.loads(ws.receive_text())
            assert msg == {"data": None, "error": "No data"}
        with tc.websocket_connect("/api/stream/image_hand/camera_info") as ws:
            msg = json.loads(ws.receive_text())
            assert msg == {"data": None, "error": "No data"}
