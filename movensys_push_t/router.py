"""HTTP / WebSocket API of movensys_push_t: robot state, top camera, moves, speed scales.

Same paths as movensys_vlm/router.py so the control page works unchanged; the VLM, memory,
Whisper, gripper, board/dice and Isaac-teleport endpoints are not here.
"""

import asyncio
import json
from typing import List

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from movensys_manipulator_moveit_config.srv import GetEefPose, MoveJoints, MovePose
from pydantic import BaseModel

import ros2_node as rn

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class MovePoseRequest(BaseModel):
    pos: List[float]  # [x, y, z]
    ori: List[float]  # [roll, pitch, yaw]

    model_config = {"json_schema_extra": {"example": {"pos": [0.4, 0.0, 0.3], "ori": [0.0, 1.57, 0.0]}}}


class MoveJointsRequest(BaseModel):
    joint_names: List[str]
    joint_values: List[float]

    model_config = {
        "json_schema_extra": {
            "example": {
                "joint_names": ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"],
                "joint_values": [0.0, -0.785, 1.571, 0.0, 0.785, 0.0],
            }
        }
    }


class ScalesRequest(BaseModel):
    vel_scale: float
    acc_scale: float

    model_config = {"json_schema_extra": {"example": {"vel_scale": 0.5, "acc_scale": 0.5}}}


# ---------------------------------------------------------------------------
# Topics — WebSocket streams
# ---------------------------------------------------------------------------

# path -> (ros_node attribute, send interval in s)
WS_STREAMS = {
    "/api/stream/eef_pose": ("latest_eef_pose", 0.1),
    "/api/stream/eef_rpy": ("latest_eef_rpy", 0.1),
    "/api/stream/joint_states": ("latest_joint_states", 0.1),
    "/api/stream/tf_static": ("latest_tf_static", 1.0),
    "/api/stream/image_top/camera_info": ("latest_top_camera_info", 0.1),
    "/api/stream/image_top/rgb": ("latest_top_rgb_image", 0.1),
}


def _add_ws_stream(path: str, attr: str, interval: float) -> None:
    async def stream(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                data = getattr(rn.ros_node, attr, None) if rn.ros_node else None
                await websocket.send_text(
                    json.dumps({"data": data, "error": None if data is not None else "No data"})
                )
                await asyncio.sleep(interval)
        except WebSocketDisconnect:
            pass

    router.add_api_websocket_route(path, stream)


for _path, (_attr, _interval) in WS_STREAMS.items():
    _add_ws_stream(_path, _attr, _interval)


# ---------------------------------------------------------------------------
# Topics — latest value (REST)
# ---------------------------------------------------------------------------

def _latest(attr: str, what: str):
    data = getattr(rn.require_node(), attr)
    if data is None:
        raise HTTPException(503, detail=f"No {what} received yet")
    return data


@router.get("/api/topics/tf_static")
def get_tf_static():
    return _latest("latest_tf_static", "tf_static")


@router.get("/api/topics/image_top/camera_info")
def get_camera_info():
    return _latest("latest_top_camera_info", "camera info")


@router.get("/api/topics/image_top/rgb")
def get_rgb_image():
    return _latest("latest_top_rgb_image", "RGB image")


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@router.get("/api/services/get_eef_pose")
def svc_get_eef_pose():
    resp = rn.call_service(rn.require_node().cli_get_eef_pose, GetEefPose.Request())
    return {"success": resp.success, "message": resp.message, "pos": list(resp.pos), "rpy": list(resp.rpy)}


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

def _move_pose(client_attr: str, body: MovePoseRequest, timeout: int = 60) -> dict:
    if len(body.pos) != 3 or len(body.ori) != 3:
        raise HTTPException(400, detail="pos and ori must each have exactly 3 elements")
    req = MovePose.Request()
    req.pos = body.pos
    req.ori = body.ori
    resp = rn.call_service(getattr(rn.require_node(), client_attr), req, timeout=timeout)
    return {"success": resp.success, "message": resp.message}


def _move_joints(client_attr: str, body: MoveJointsRequest, timeout: int = 60) -> dict:
    if len(body.joint_names) != len(body.joint_values):
        raise HTTPException(400, detail="joint_names and joint_values must have the same length")
    req = MoveJoints.Request()
    req.joint_names = body.joint_names
    req.joint_values = body.joint_values
    resp = rn.call_service(getattr(rn.require_node(), client_attr), req, timeout=timeout)
    return {"success": resp.success, "message": resp.message}


@router.post("/api/move/absolute_cartesian_base")
def absolute_cartesian_base(body: MovePoseRequest):
    return _move_pose("cli_abs_base_cart", body)


@router.post("/api/move/relative_cartesian_base")
def relative_cartesian_base(body: MovePoseRequest):
    return _move_pose("cli_rel_base_cart", body)


@router.post("/api/move/relative_cartesian_tool")
def relative_cartesian_tool(body: MovePoseRequest):
    return _move_pose("cli_rel_tool_cart", body)


@router.post("/api/move/absolute_joint_pose")
def absolute_joint_pose(body: MovePoseRequest):
    return _move_pose("cli_abs_base_joint", body)


@router.post("/api/move/joint_absolute")
def joint_absolute(body: MoveJointsRequest):
    return _move_joints("cli_joint_abs", body)


@router.post("/api/move/joint_relative")
def joint_relative(body: MoveJointsRequest):
    return _move_joints("cli_joint_rel", body)


# ---------------------------------------------------------------------------
# Scales (vel / acc)
# ---------------------------------------------------------------------------

@router.get("/api/config/scales")
def get_scales():
    return rn.get_scales()


@router.post("/api/config/scales")
def set_scales(body: ScalesRequest):
    if not (0.0 < body.vel_scale <= 1.0):
        raise HTTPException(400, detail="vel_scale must be in (0, 1]")
    if not (0.0 < body.acc_scale <= 1.0):
        raise HTTPException(400, detail="acc_scale must be in (0, 1]")
    return rn.set_scales(body.vel_scale, body.acc_scale)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/api/health")
def health():
    return {"status": "ok", "ros_node": rn.ros_node is not None}
