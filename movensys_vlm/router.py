import asyncio
import base64
import io
import json
from typing import List, Optional

from PIL import Image

import std_srvs.srv
from movensys_manipulator_moveit_config.srv import GetEefPose, MovePose, MoveJoints

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import memory_client
import ros2_node as rn
import vlm_client
import whisper_client

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
    camera: str = "top"   # "top", "hand", or "none"
    # Optional caller-supplied image. When provided, this overrides the
    # camera lookup — the orchestrator does not consult ros_node at all
    # and passes this base64 string straight to vlm_client.infer. Lets
    # browser clients send a captured screenshot of their own UI (e.g.
    # robopoly's rendered game board) without needing a physical camera.
    image_b64: Optional[str] = None
    prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    max_tokens: int = 128
    temperature: float = 0.2
    rotate180: bool = False
    # Per-client namespace for the stored system prompt (e.g. "vlm",
    # "robopoly"). Falls back to the shared "default" slot when omitted.
    client: Optional[str] = None

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

# YOLO debug overlays — consumed by the robopoly board pane while
# pick_and_place runs. Robopoly is served on :7999 but cross-origins
# to :8000 for ROS-fed streams (same as joint_states / eef_pose).


@router.websocket("/api/stream/yolo_dice_detector/debug_image")
async def ws_yolo_dice_debug(websocket: WebSocket):
    await _ws_stream(websocket, "latest_yolo_dice_debug_image", interval=0.1)


@router.websocket("/api/stream/yolo_cube_detector/debug_image")
async def ws_yolo_cube_debug(websocket: WebSocket):
    await _ws_stream(websocket, "latest_yolo_cube_debug_image", interval=0.1)


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
def get_dice_pose():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_dice_pose
    if data is None:
        raise HTTPException(503, detail="No /piece_2 pose received yet")
    return data

# YOLO-detected dice face value, published on /yolo_dice_detector/dice_number


@router.get("/api/topics/dice_number")
def get_dice_number():
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    data = rn.ros_node.latest_dice_number
    if data is None:
        raise HTTPException(503, detail="No dice number received yet")
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
# Isaac Sim — object teleport sync
# ---------------------------------------------------------------------------

class IsaacSpawnTargetRequest(BaseModel):
    # "dice", "red_cube", or "green_cube" — maps to /{dice,red,green}_pose_sub.
    target: str
    # Optional explicit pose. When omitted, the orchestrator falls back to
    # the latest EEF pose with the apriltag axis swap
    # (x_iso = -y_base, y_iso = x_base) so the Isaac frame matches the
    # manipulator base frame.
    pose: Optional[dict] = None
    # Override z when the pose is derived from EEF. EEF z is the gripper
    # height (well above the table during a pick), so a fixed table-relative
    # z gives a more useful spawn point. Mirrors `z_target_pose_spawn` in
    # apriltag_pick_and_place.cpp (yaml default 0.07).
    z: Optional[float] = None

    model_config = {
        "json_schema_extra": {
            "example": {"target": "dice", "z": 0.07}
        }
    }


@router.post("/api/isaac/spawn_target")
def isaac_spawn_target(body: IsaacSpawnTargetRequest):
    """Publish a Pose to /{dice,red,green}_pose_sub so Isaac Sim teleports
    the matching object. Called by movensys_robopoly's `pick_and_place.py`
    immediately before the gripper closes on a pickup, so the simulated
    counterpart of the dice / cube ends up under the simulated gripper —
    same pattern as `apriltag_pick_and_place.cpp`'s target_spawn block.
    """
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    if body.pose is not None:
        pose = body.pose
    else:
        eef = rn.ros_node.latest_eef_pose
        if eef is None:
            raise HTTPException(503, detail="No EEF pose received yet")
        ep, eo = eef["position"], eef["orientation"]
        pose = {
            "position": {
                "x": -float(ep["y"]),
                "y": float(ep["x"]),
                "z": float(body.z) if body.z is not None else float(ep["z"]),
            },
            "orientation": dict(eo),
        }
    try:
        topic = rn.ros_node.publish_isaac_target_pose(body.target, pose)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    return {"target": body.target, "topic": topic, "pose": pose}


# ---------------------------------------------------------------------------
# VLM inference
# ---------------------------------------------------------------------------

@router.post("/api/vlm/infer")
async def vlm_infer(body: VlmInferRequest):
    if rn.ros_node is None:
        raise HTTPException(503, detail="ROS node not running")

    # Caller-supplied image overrides the camera lookup entirely. Useful
    # for browser clients that want the VLM to "see" their own rendered
    # UI instead of (or in addition to) the physical workspace camera.
    img = None
    if body.image_b64:
        image_b64: Optional[str] = body.image_b64
    else:
        if body.camera == "hand":
            img = rn.ros_node.latest_hand_rgb_image
        elif body.camera == "top":
            img = rn.ros_node.latest_top_rgb_image
        elif body.camera == "none":
            img = None
        else:
            raise HTTPException(400, detail="camera must be 'top', 'hand', or 'none'")
        image_b64 = None
        if img is not None:
            image_b64 = img["data"]
    if image_b64 is not None and body.rotate180:
        pil_img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
        pil_img = pil_img.rotate(180)
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG")
        image_b64 = base64.b64encode(buf.getvalue()).decode()

    user_prompt = body.prompt or "Report the tokens on the board."

    error: Optional[str] = None
    result: Optional[str] = None
    try:
        result = await vlm_client.infer(
            image_b64,
            user_prompt=user_prompt,
            system_prompt=body.system_prompt,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            client_id=body.client,
        )
    except Exception as exc:
        error = f"VLM inference failed: {exc}"

    return {
        "camera": body.camera,
        "width": img.get("width") if img else None,
        "height": img.get("height") if img else None,
        "image": image_b64,
        "encoding": img.get("encoding") if img else None,
        "user_prompt": user_prompt,
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
def vlm_get_system_prompt(client: Optional[str] = None):
    return {
        "system_prompt": vlm_client.get_system_prompt(client),
        "default_system_prompt": vlm_client.DEFAULT_SYSTEM_PROMPT,
        "client": client or vlm_client.DEFAULT_CLIENT,
    }


@router.put("/api/vlm/system_prompt")
def vlm_set_system_prompt(body: VlmSystemPromptRequest, client: Optional[str] = None):
    if not body.system_prompt.strip():
        raise HTTPException(400, detail="system_prompt must not be empty")
    return {
        "system_prompt": vlm_client.set_system_prompt(body.system_prompt, client),
        "client": client or vlm_client.DEFAULT_CLIENT,
    }


@router.delete("/api/vlm/system_prompt")
def vlm_reset_system_prompt(client: Optional[str] = None):
    return {
        "system_prompt": vlm_client.reset_system_prompt(client),
        "client": client or vlm_client.DEFAULT_CLIENT,
    }


# ---------------------------------------------------------------------------
# VLM memory (vector DB)
# ---------------------------------------------------------------------------

@router.get("/api/vlm/memory")
async def vlm_memory_stats():
    return {"count": await memory_client.count(), "enabled": memory_client.is_enabled()}


@router.delete("/api/vlm/memory")
async def vlm_memory_clear():
    return await memory_client.clear()


# ---------------------------------------------------------------------------
# Whisper STT
# ---------------------------------------------------------------------------

@router.post("/api/whisper/transcribe")
async def whisper_transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = None,
):
    audio_bytes = await file.read()
    try:
        text = await whisper_client.transcribe(
            audio_bytes,
            filename=file.filename or "audio.wav",
            content_type=file.content_type or "audio/wav",
            language=language,
        )
        return {"text": text, "error": None}
    except Exception as exc:
        return {"text": None, "error": f"transcription failed: {exc}"}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/api/health")
def health():
    return {"status": "ok", "ros_node": rn.ros_node is not None}
