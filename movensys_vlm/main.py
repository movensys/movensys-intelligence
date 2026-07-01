import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.openapi.utils import get_openapi

from ros2_node import start_ros_node
from router import router

_log = logging.getLogger(__name__)


def _maybe_start_phoenix() -> None:
    """Export OpenAI-client spans to a standalone Phoenix collector when
    PHOENIX_TRACING is truthy. Off by default — production / demo runs
    pay zero cost.

    Run Phoenix separately, e.g.:
        docker run -d --rm -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest
    Then set PHOENIX_COLLECTOR_ENDPOINT to its OTel ingest URL (defaults
    to http://localhost:6006, which the Phoenix image accepts over HTTP).
    The UI is at http://<phoenix-host>:6006.

    Traces only cover the OpenAI-client side (vlm_client.infer and
    whisper_client.transcribe). They do NOT include GPU-side inference
    cost — that's whatever vLLM/Whisper server logs separately.
    """
    flag = os.environ.get("PHOENIX_TRACING", "").strip().lower()
    if flag not in ("1", "true", "yes", "y", "on"):
        return
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "").strip() or "http://localhost:6006/v1/traces"
    project = os.environ.get("PHOENIX_PROJECT_NAME", "").strip() or "movensys-vlm"
    try:
        from phoenix.otel import register
    except ImportError as exc:
        _log.warning(
            "PHOENIX_TRACING=%s but phoenix.otel not available: %s",
            flag, exc,
        )
        return
    try:
        register(endpoint=endpoint, project_name=project, batch=True, auto_instrument=True)
        _log.warning(
            "Phoenix tracing exporting to %s (project=%s)", endpoint, project,
        )
    except Exception:
        _log.exception("failed to start Phoenix tracing")


_maybe_start_phoenix()


class SafeStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1000})
            return
        await super().__call__(scope, receive, send)


app = FastAPI(
    title="Movensys Manipulator API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


_WS_STREAMS = {
    "/api/stream/eef_pose": {
        "summary": "WS — EEF Pose",
        "description": "WebSocket stream of `/wmx/moveit2/eef_pose` (geometry_msgs/PoseStamped). "
                       "Connect with `ws://<host>/api/stream/eef_pose`. "
                       "Sends `{\"data\": {\"position\": {x,y,z}, \"orientation\": {x,y,z,w}}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/eef_rpy": {
        "summary": "WS — EEF RPY",
        "description": "WebSocket stream of `/wmx/moveit2/eef_rpy` (geometry_msgs/Vector3Stamped). "
                       "Sends `{\"data\": {\"roll\", \"pitch\", \"yaw\"}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/joint_states": {
        "summary": "WS — Joint States",
        "description": "WebSocket stream of `/joint_states` (sensor_msgs/JointState). "
                       "Sends `{\"data\": {\"name\", \"position\", \"velocity\", \"effort\"}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/tf_static": {
        "summary": "WS — TF Static",
        "description": "WebSocket stream of `/tf_static` (tf2_msgs/TFMessage). "
                       "Sends `{\"data\": [...transforms], \"error\": null}` at ~1 Hz.",
    },
    "/api/stream/image_top/camera_info": {
        "summary": "WS — Top Camera Info",
        "description": "WebSocket stream of `/image_top/camera_info` (sensor_msgs/CameraInfo). "
                       "Sends `{\"data\": {...}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/image_top/depth": {
        "summary": "WS — Top Depth Image",
        "description": "WebSocket stream of `/image_top/depth` (sensor_msgs/Image, 32FC1 colorized). "
                       "Sends `{\"data\": {...}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/image_top/rgb": {
        "summary": "WS — Top RGB Image",
        "description": "WebSocket stream of `/image_top/rgb` (sensor_msgs/Image, RGB8). "
                       "Sends `{\"data\": {...}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/image_hand/camera_info": {
        "summary": "WS — Hand Camera Info",
        "description": "WebSocket stream of `/image_hand/camera_info` (sensor_msgs/CameraInfo). "
                       "Sends `{\"data\": {...}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/image_hand/depth": {
        "summary": "WS — Hand Depth Image",
        "description": "WebSocket stream of `/image_hand/depth` (sensor_msgs/Image, 32FC1 colorized). "
                       "Sends `{\"data\": {...}, \"error\": null}` at ~10 Hz.",
    },
    "/api/stream/image_hand/rgb": {
        "summary": "WS — Hand RGB Image",
        "description": "WebSocket stream of `/image_hand/rgb` (sensor_msgs/Image, RGB8). "
                       "Sends `{\"data\": {...}, \"error\": null}` at ~10 Hz.",
    },
}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema.setdefault("paths", {})
    for path, meta in _WS_STREAMS.items():
        schema["paths"][path] = {
            "get": {
                "tags": ["WebSocket Streams"],
                "summary": meta["summary"],
                "description": meta["description"],
                "responses": {"101": {"description": "Switching Protocols — WebSocket upgrade"}},
            }
        }
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/cameras", include_in_schema=False)
def cameras_page():
    return FileResponse("/app/static/cameras.html")


@app.get("/vlm", include_in_schema=False)
def vlm_page():
    return FileResponse("/app/static/vlm.html")


@app.on_event("startup")
def startup():
    start_ros_node()


app.mount("/", SafeStaticFiles(directory="/app/static", html=True), name="static")
