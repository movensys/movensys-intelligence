"""Movensys PushT — web UI and API for moving the robot and watching the top camera.

No AI models: a ROS 2 node (ros2_node.py) talks to the MoveIt2 services of
movensys_manipulator_moveit_config and subscribes to the robot state and the
9a scene's camera_top_link (/image_top/*). router.py exposes them over
REST/WebSocket, static/index.html is the control page with the camera (/).
imitation_node.py / imitation_router.py add the PushT imitation-learning workflow (planar guard,
pixel scorer, episode recorder and manager), with its page at /imitation.html.

Started by docker/movensys_push_t-entrypoint.sh:
    uvicorn main:app --host 0.0.0.0 --port ${PUSH_T_PORT:-7000}
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from ros2_node import start_ros_node
from imitation_router import router as imitation_router
from router import WS_STREAMS, router

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_ros_node()
    yield


app = FastAPI(
    title="Movensys PushT API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(imitation_router)


def custom_openapi():
    """List the WebSocket streams in /docs (OpenAPI has no WebSocket type)."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    for path, (attr, interval) in WS_STREAMS.items():
        schema.setdefault("paths", {})[path] = {
            "get": {
                "tags": ["WebSocket Streams"],
                "summary": f"WS — {path.removeprefix('/api/stream/')}",
                "description": f"WebSocket stream of `{attr}` every {interval} s: "
                               "`{\"data\": ..., \"error\": null}`.",
                "responses": {"101": {"description": "Switching Protocols — WebSocket upgrade"}},
            }
        }
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.get("/health", tags=["System"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "movensys_push_t",
        "manipulator_model": os.environ.get("MANIPULATOR_MODEL", "dobot_cr3a_custom_tool"),
    }


class SafeStaticFiles(StaticFiles):
    """StaticFiles mounted at / would otherwise error on stray WebSocket connections."""

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1000})
            return
        await super().__call__(scope, receive, send)


app.mount("/", SafeStaticFiles(directory=STATIC, html=True), name="static")
