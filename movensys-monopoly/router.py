"""HTTP surface (PRD §5). M0 stage only wires health + stub-mode routes.

Subsequent milestones add game control, dice, money, property, effects,
jail, cameras, debug. All routes live under /api.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from utils.logging import current_event_id

api_router = APIRouter(prefix="/api")


@api_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@api_router.get("/robot/health")
async def robot_health(request: Request) -> dict[str, object]:
    adapter = request.app.state.robot_adapter
    return adapter.health()


@api_router.get("/stt/health")
async def stt_health(request: Request) -> dict[str, object]:
    return request.app.state.stt_adapter.health()


@api_router.get("/llm/health")
async def llm_health(request: Request) -> dict[str, object]:
    return request.app.state.llm_adapter.health()


@api_router.get("/ros2/health")
async def ros2_health(request: Request) -> dict[str, object]:
    bridge = request.app.state.ros2
    return {"enabled": bridge.enabled, "isaac_topic": bridge.isaac_card_spawn_topic}


@api_router.get("/_event_id")
async def current_event() -> dict[str, str | None]:
    """Diagnostic: return the event_id bound to this request."""
    return {"event_id": current_event_id()}
