import asyncio
import base64
import io
import json
from typing import List, Optional

from PIL import Image

import std_srvs.srv
from movensys_manipulator_moveit_config.srv import GetEefPose, MovePose, MoveJoints

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import ros2_node as rn
import vlm_client

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class MovePoseRequest(BaseModel):
    pos: List[float]   # [x, y, z]
    ori: List[float]   # [roll, pitch, yaw]

    model_config = {
        "json_schema_extra": {
            "example": {
                "pos": [0.4, 0.0, 0.3],
                "ori": [0.0, 1.57, 0.0],
            }
        }
    }

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

class GripperRequest(BaseModel):
    data: bool

    model_config = {
        "json_schema_extra": {
            "example": {"data": True}
        }
    }

class ScalesRequest(BaseModel):
    vel_scale: float
    acc_scale: float

    model_config = {
        "json_schema_extra": {
            "example": {"vel_scale": 0.5, "acc_scale": 0.5}
        }
    }

class VlmInferRequest(BaseModel):
    camera: str = "top"   # "top" or "hand"
    prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    max_tokens: int = 512
    temperature: float = 0.2
    rotate180: bool = False

    model_config = {
        "json_schema_extra": {
            "example": {
                "camera": "top",
                "prompt": "Which player tokens are on the board and where?",
                "max_tokens": 512,
                "temperature": 0.2,
                "rotate180": False,
            }
        }
    }


# ---------------------------------------------------------------------------
# Topics — WebSocket stream
# ---------------------------------------------------------------------------

async def _ws_stream(websocket: WebSocket, attr: str, interval: float = 0.1):
    await websocket.accept()
    try:
        while True:
            data = getattr(rn.ros_node, attr, None) if rn.ros_node else None
            await websocket.send_text(json.dumps({"data": data, "error": None if data is not None else "No data"}))
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass

@router.websocket("/api/stream/eef_pose")
async def ws_eef_pose(websocket: WebSocket):
    await _ws_stream(websocket, "latest_eef_pose")

@router.websocket("/api/stream/eef_rpy")
async def ws_eef_rpy(websocket: WebSocket):
    await _ws_stream(websocket, "latest_eef_rpy")

@router.websocket("/api/stream/joint_states")
async def ws_joint_states(websocket: WebSocket):
    await _ws_stream(websocket, "latest_joint_states")

@router.websocket("/api/stream/tf_static")
async def ws_tf_static(websocket: WebSocket):
    await _ws_stream(websocket, "latest_tf_static", interval=1.0)

@router.websocket("/api/stream/image_top/camera_info")
async def ws_camera_info(websocket: WebSocket):
    await _ws_stream(websocket, "latest_top_camera_info")

@router.websocket("/api/stream/image_top/depth")
async def ws_depth(websocket: WebSocket):
    await _ws_stream(websocket, "latest_top_depth_image", interval=0.1)

@router.websocket("/api/stream/image_top/rgb")
async def ws_rgb(websocket: WebSocket):
    await _ws_stream(websocket, "latest_top_rgb_image", interval=0.1)

@router.websocket("/api/stream/image_hand/camera_info")
async def ws_hand_camera_info(websocket: WebSocket):
    await _ws_stream(websocket, "latest_hand_camera_info")

@router.websocket("/api/stream/image_hand/depth")
async def ws_hand_depth(websocket: WebSocket):
    await _ws_stream(websocket, "latest_hand_depth_image", interval=0.1)

@router.websocket("/api/stream/image_hand/rgb")
async def ws_hand_rgb(websocket: WebSocket):
    await _ws_stream(websocket, "latest_hand_rgb_image", interval=0.1)


# ---------------------------------------------------------------------------
# Image top — REST snapshots
# ---------------------------------------------------------------------------

@router.get("/api/topics/tf_static")
def get_tf_static():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_tf_static
    if data is None:
        raise HTTPException(503, detail="No tf_static received yet")
    return data

# Yolo result is published at /tf side. 
# User can check the result using `ros2 topic echo /tf`
@router.get("/api/topics/yolo_tf")
def get_yolo_tf():
    # node가 없을 때.
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_yolo_tf
    # latest_yolo_tf의 값이 업데이트 되지 않았을 때.
    if not data:
        raise HTTPException(503, detail="No yolo /tf frames received yet")
    return data

# Subscribing green-cube position from IsaacSim 
@router.get("/api/topics/piece_1")
def get_piece_1_pose():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_piece_1_pose
    if data is None:
        raise HTTPException(503, detail="No /piece_1 pose received yet")
    return data

# Subscribing red-cube position from IsaacSim 
@router.get("/api/topics/piece_2")
def get_piece_2_pose():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_piece_2_pose
    if data is None:
        raise HTTPException(503, detail="No /piece_2 pose received yet")
    return data

# Subscribing dice position from IsaacSim 
@router.get("/api/topics/dice")
def get_piece_2_pose():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_dice_pose
    if data is None:
        raise HTTPException(503, detail="No /piece_2 pose received yet")
    return data

@router.get("/api/topics/image_top/camera_info")
def get_camera_info():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_top_camera_info
    if data is None:
        raise HTTPException(503, detail="No camera_info received yet")
    return data

@router.get("/api/topics/image_top/depth")
def get_depth_image():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_top_depth_image
    if data is None:
        raise HTTPException(503, detail="No depth image received yet")
    return data

@router.get("/api/topics/image_top/rgb")
def get_rgb_image():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_top_rgb_image
    if data is None:
        raise HTTPException(503, detail="No RGB image received yet")
    return data

@router.get("/api/topics/image_hand/camera_info")
def get_hand_camera_info():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_hand_camera_info
    if data is None:
        raise HTTPException(503, detail="No hand camera_info received yet")
    return data

@router.get("/api/topics/image_hand/depth")
def get_hand_depth_image():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_hand_depth_image
    if data is None:
        raise HTTPException(503, detail="No hand depth image received yet")
    return data

@router.get("/api/topics/image_hand/rgb")
def get_hand_rgb_image():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_hand_rgb_image
    if data is None:
        raise HTTPException(503, detail="No hand RGB image received yet")
    return data


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@router.get("/api/services/get_eef_pose")
def svc_get_eef_pose():
    resp = rn.call_service(rn.ros_node.cli_get_eef_pose, GetEefPose.Request())
    return {"success": resp.success, "message": resp.message, "pos": list(resp.pos), "rpy": list(resp.rpy)}

@router.post("/api/services/gripper")
def svc_gripper(body: GripperRequest):
    resp = rn.call_service(rn.ros_node.cli_gripper, std_srvs.srv.SetBool.Request(data=body.data))
    return {"success": resp.success, "message": resp.message}


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

def _move_pose(client, body: MovePoseRequest, timeout: int = 60) -> dict:
    if len(body.pos) != 3 or len(body.ori) != 3:
        raise HTTPException(400, detail="pos and ori must each have exactly 3 elements")
    req = MovePose.Request()
    req.pos = body.pos
    req.ori = body.ori
    resp = rn.call_service(client, req, timeout=timeout)
    return {"success": resp.success, "message": resp.message}

def _move_joints(client, body: MoveJointsRequest, timeout: int = 60) -> dict:
    if len(body.joint_names) != len(body.joint_values):
        raise HTTPException(400, detail="joint_names and joint_values must have the same length")
    req = MoveJoints.Request()
    req.joint_names = body.joint_names
    req.joint_values = body.joint_values
    resp = rn.call_service(client, req, timeout=timeout)
    return {"success": resp.success, "message": resp.message}

@router.post("/api/move/absolute_cartesian_base")
def absolute_cartesian_base(body: MovePoseRequest):
    return _move_pose(rn.ros_node.cli_abs_base_cart, body)

@router.post("/api/move/relative_cartesian_base")
def relative_cartesian_base(body: MovePoseRequest):
    return _move_pose(rn.ros_node.cli_rel_base_cart, body)

@router.post("/api/move/relative_cartesian_tool")
def relative_cartesian_tool(body: MovePoseRequest):
    return _move_pose(rn.ros_node.cli_rel_tool_cart, body)

@router.post("/api/move/absolute_joint_pose")
def absolute_joint_pose(body: MovePoseRequest):
    return _move_pose(rn.ros_node.cli_abs_base_joint, body)

@router.post("/api/move/joint_absolute")
def joint_absolute(body: MoveJointsRequest):
    return _move_joints(rn.ros_node.cli_joint_abs, body)

@router.post("/api/move/joint_relative")
def joint_relative(body: MoveJointsRequest):
    return _move_joints(rn.ros_node.cli_joint_rel, body)


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
# VLM inference
# ---------------------------------------------------------------------------

def _classify_token(label: str, pose: Optional[dict], board_pose: dict) -> dict:
    """Run geometry classification for one token; return a serializable dict."""
    if pose is None:
        return {"label": label, "status": "unavailable",
                "row": None, "col": None, "world": None}
    info = mg.classify_piece(
        (pose["position"]["x"], pose["position"]["y"]),
        (board_pose["position"]["x"], board_pose["position"]["y"]),
        (
            board_pose["orientation"]["x"],
            board_pose["orientation"]["y"],
            board_pose["orientation"]["z"],
            board_pose["orientation"]["w"],
        ),
    )
    return {
        "label": label,
        "status": info["status"],
        "row": info["row"],
        "col": info["col"],
        "world": {"x": pose["position"]["x"], "y": pose["position"]["y"]},
        "local": {"x": info["local_x"], "y": info["local_y"]},
    }


def _format_token_lines(tokens: List[dict]) -> str:
    lines = []
    for t in tokens:
        if t["status"] == "unavailable":
            lines.append(f"- {t['label']}: pose unavailable")
        elif t["status"] == "on_board":
            lines.append(f"- {t['label']}: status=on_board, row={t['row']}, col={t['col']}")
        else:
            lines.append(f"- {t['label']}: status={t['status']}")
    return "\n".join(lines) if lines else "(no tokens)"


@router.post("/api/vlm/infer")
async def vlm_infer(body: VlmInferRequest):
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")

    if body.camera == "hand":
        img = rn.ros_node.latest_hand_rgb_image
    elif body.camera == "top":
        img = rn.ros_node.latest_top_rgb_image
    else:
        raise HTTPException(400, detail="camera must be 'top' or 'hand'")

    if img is None:
        raise HTTPException(503, detail=f"No RGB image available for camera '{body.camera}'")

    image_b64 = img["data"]
    if body.rotate180:
        pil_img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
        pil_img = pil_img.rotate(180)
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG")
        image_b64 = base64.b64encode(buf.getvalue()).decode()

    board_pose = rn.ros_node.latest_board_pose
    tokens: List[dict] = []
    if board_pose is not None:
        tokens.append(_classify_token("piece_1", rn.ros_node.latest_piece_1_pose, board_pose))
        tokens.append(_classify_token("piece_2", rn.ros_node.latest_piece_2_pose, board_pose))

    sensor_block = _format_token_lines(tokens) if tokens else "(no /board pose received yet — fall back to vision)"
    base_prompt = body.prompt or "Report the tokens on the board."
    user_prompt = (
        f"Sensor data (from /piece_1, /piece_2, /board topics):\n{sensor_block}\n\n"
        f"{base_prompt}"
    )

    error: Optional[str] = None
    result: Optional[str] = None
    try:
        result = await vlm_client.infer(
            image_b64,
            user_prompt=user_prompt,
            system_prompt=body.system_prompt,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
        )
    except Exception as exc:
        error = f"VLM inference failed: {exc}"

    return {
        "camera": body.camera,
        "width": img.get("width"),
        "height": img.get("height"),
        "image": image_b64,
        "encoding": img.get("encoding"),
        "user_prompt": user_prompt,
        "tokens": tokens,
        "response": result if result is not None else (error or ""),
        "error": error,
    }


class VlmSystemPromptRequest(BaseModel):
    system_prompt: str

    model_config = {
        "json_schema_extra": {
            "example": {"system_prompt": "You are a vision assistant for a simplified Monopoly game…"}
        }
    }


@router.get("/api/vlm/system_prompt")
def vlm_get_system_prompt():
    return {
        "system_prompt": vlm_client.get_system_prompt(),
        "default_system_prompt": vlm_client.DEFAULT_SYSTEM_PROMPT,
    }


@router.put("/api/vlm/system_prompt")
def vlm_set_system_prompt(body: VlmSystemPromptRequest):
    if not body.system_prompt.strip():
        raise HTTPException(400, detail="system_prompt must not be empty")
    return {"system_prompt": vlm_client.set_system_prompt(body.system_prompt)}


@router.delete("/api/vlm/system_prompt")
def vlm_reset_system_prompt():
    return {"system_prompt": vlm_client.reset_system_prompt()}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/api/health")
def health():
    return {"status": "ok", "ros_node": rn.ros_node is not None}
