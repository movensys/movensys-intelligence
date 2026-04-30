"""FastAPI entry point for movensys-monopoly (PRD §3, §5, §10).

Responsibilities at M0:
- Configure JSON logger
- Build adapters from env (stub when URL empty)
- Expose /api/health and adapter health routes
- Guard /api/debug/* with MONOPOLY_DEBUG_ROUTES
- Per-request event_id middleware
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from adapters import LLMAdapter, RobotAdapter, STTAdapter
from game.events import EventBus
from game.manager import GameManager
from ros2_node import Ros2Bridge
from router import api_router
from utils import logging as jlog

log = logging.getLogger("monopoly")


def _debug_routes_enabled() -> bool:
    return os.environ.get("MONOPOLY_DEBUG_ROUTES", "true").lower() not in ("false", "0", "no")


@asynccontextmanager
async def lifespan(app: FastAPI):
    jlog.configure()
    app.state.stt_adapter = STTAdapter.from_env()
    app.state.llm_adapter = LLMAdapter.from_env()
    app.state.robot_adapter = RobotAdapter.from_env()
    app.state.debug_routes_enabled = _debug_routes_enabled()
    app.state.event_bus = EventBus()
    app.state.game = GameManager(bus=app.state.event_bus)
    app.state.ros2 = Ros2Bridge()
    app.state.ros2.start()
    # Bridge the Chance/CC card draws onto the Isaac spawn topic (§7.3.6).
    # No-op when the bridge stayed in disabled mode (dev laptops, CI).
    app.state.game.card_spawn_hook = app.state.ros2.publish_card_spawn
    log.info(
        "startup",
        extra={
            "stt_mode": app.state.stt_adapter.mode,
            "llm_mode": app.state.llm_adapter.mode,
            "robot_mode": app.state.robot_adapter.mode,
            "ros2_enabled": app.state.ros2.enabled,
            "debug_routes": app.state.debug_routes_enabled,
        },
    )
    yield
    app.state.ros2.stop()
    log.info("shutdown")


app = FastAPI(title="movensys-monopoly", lifespan=lifespan)


@app.middleware("http")
async def event_id_middleware(request: Request, call_next):
    jlog.new_event_id()
    response = await call_next(request)
    eid = jlog.current_event_id()
    if eid:
        response.headers["X-Event-Id"] = eid
    return response


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static") or path.startswith("/assets"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def debug_routes_guard(request: Request, call_next):
    if request.url.path.startswith("/api/debug"):
        enabled = getattr(request.app.state, "debug_routes_enabled", _debug_routes_enabled())
        if not enabled:
            eid = jlog.current_event_id() or jlog.new_event_id()
            return JSONResponse(
                status_code=404,
                headers={"X-Event-Id": eid},
                content={
                    "error": {
                        "code": "NOT_FOUND",
                        "message": "debug routes disabled",
                        "event_id": eid,
                    }
                },
            )
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error_envelope(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert HTTPException into the PRD §4.7 error envelope."""
    eid = jlog.current_event_id() or jlog.new_event_id()
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {
            "error": {
                "code": detail.get("code", "BAD_REQUEST"),
                "message": detail.get("message", ""),
                "details": detail.get("details", {}),
                "event_id": eid,
            }
        }
    else:
        body = {
            "error": {
                "code": "BAD_REQUEST" if exc.status_code < 500 else "INTERNAL",
                "message": str(detail) if detail else "",
                "details": {},
                "event_id": eid,
            }
        }
    return JSONResponse(status_code=exc.status_code, headers={"X-Event-Id": eid}, content=body)


app.include_router(api_router)

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_static_dir / "index.html")

    @app.get("/cameras")
    async def cameras() -> FileResponse:
        return FileResponse(_static_dir / "cameras.html")
