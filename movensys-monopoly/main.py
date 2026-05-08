"""FastAPI entry point for movensys-monopoly."""
# app.state, app.mount, app.include_router(api_router)
# For app.mount("/static", StaticFiles(directory=<Path class>), name="static") 이걸 외워두면 좋다.


from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from adapters import LLMAdapter, RobotAdapter, STTAdapter
from game.events import EventBus
from game.manager import GameManager
from ros2_node import Ros2Bridge
from router import api_router

log = logging.getLogger("monopoly")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app.state.stt_adapter = STTAdapter.from_env()
    app.state.llm_adapter = LLMAdapter.from_env()
    app.state.robot_adapter = RobotAdapter.from_env()
    app.state.event_bus = EventBus()
    app.state.game = GameManager(bus=app.state.event_bus)
    app.state.ros2 = Ros2Bridge()
    app.state.ros2.start()
    log.info(
        "startup",
        extra={
            "stt_mode": app.state.stt_adapter.mode,
            "llm_mode": app.state.llm_adapter.mode,
            "robot_mode": app.state.robot_adapter.mode,
            "ros2_enabled": app.state.ros2.enabled,
        },
    )
    yield
    app.state.ros2.stop()
    log.info("shutdown")


app = FastAPI(title="movensys-monopoly", lifespan=lifespan)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static") or path.startswith("/assets"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


app.include_router(api_router)

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    # directory mount하기
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_static_dir / "index.html")

    @app.get("/cameras")
    async def cameras() -> FileResponse:
        return FileResponse(_static_dir / "cameras.html")
