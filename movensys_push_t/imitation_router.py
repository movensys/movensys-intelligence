"""HTTP / WebSocket API of the PushT imitation features (imitation_node.py), under /api/imitation."""

from __future__ import annotations

import asyncio
import json
import os
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from movensys_manipulator_moveit_config.srv import MovePose
from pydantic import BaseModel

import imitation_core as ic
import imitation_node as inode
import ros2_node as rn

router = APIRouter(prefix="/api/imitation", tags=["Imitation"])


def node() -> inode.ImitationNode:
    if rn.imitation_node is None:
        raise HTTPException(503, detail="imitation node not running")
    return rn.imitation_node


def _bad(exc: Exception):
    raise HTTPException(409, detail=str(exc))


class GuardBody(BaseModel):
    enabled: bool


class LiftBody(BaseModel):
    up: bool


class SpeedBody(BaseModel):
    max_speed: float


class TargetBody(BaseModel):
    u: Optional[float] = None   # full-frame pixel of the top camera
    v: Optional[float] = None
    x: Optional[float] = None   # or a planning-frame point
    y: Optional[float] = None


class RoiBody(BaseModel):
    roi: Optional[List[int]] = None   # [x0, y0, w, h] in the camera frame; None: auto (push area)


class ThresholdBody(BaseModel):
    hue: List[int]
    sat_min: int
    val: List[int]


class PickBody(BaseModel):
    u: float
    v: float


class FeedbackBody(BaseModel):
    mode: str


class SessionBody(BaseModel):
    dataset: str = "pusht_cr3a_sim"
    operator: str = ""
    n_episodes: int = 1
    input_device: str = "teleop"     # teleop | policy
    episode_seconds: float = 30.0    # teleop: at most; policy: always the full duration
    start_from_home: bool = True     # lift, go to home, lower before each episode
    wait_before_record: bool = True  # wait for "record" before each episode


# --------------------------------------------------------------------------- status

@router.get("/status")
def status():
    return node().status()


@router.websocket("/ws/status")
async def ws_status(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            n = rn.imitation_node
            await ws.send_text(json.dumps(n.status() if n else {"error": "imitation node not running"},
                                          default=lambda o: None))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/input")
async def ws_input(ws: WebSocket):
    """Teleop input at the browser's rate: ``{"sx", "sy", "deadman"}`` (stick, screen axes) or
    ``{"u", "v"}`` (drag target on the camera image). Silence = hold (the guard's staleness)."""
    await ws.accept()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            n = rn.imitation_node
            if n is None:
                continue
            if "u" in msg:
                xy = n.unproject(float(msg["u"]), float(msg["v"]), n.tip_z())
                if xy is not None:
                    n.set_ui_target(*xy)
            else:
                sx = max(-1.0, min(1.0, float(msg.get("sx", 0.0))))
                sy = max(-1.0, min(1.0, float(msg.get("sy", 0.0))))
                n.set_stick(sx, sy, bool(msg.get("deadman", False)))
    except (WebSocketDisconnect, json.JSONDecodeError, ValueError):
        pass


# ---------------------------------------------------------------------------- guard

@router.post("/guard")
def guard(body: GuardBody):
    try:
        return {"result": node().set_enabled(body.enabled)}
    except ValueError as exc:
        _bad(exc)


@router.post("/guard/lift")
def lift(body: LiftBody):
    node().set_lift(body.up)
    return {"lift_goal": "up" if body.up else "down"}


@router.post("/guard/relatch")
def relatch():
    try:
        node().relatch()
    except ValueError as exc:
        _bad(exc)
    return {"result": "plane re-latches on the next cycle"}


@router.post("/guard/speed")
def speed(body: SpeedBody):
    if not 0.01 <= body.max_speed <= 0.25:
        raise HTTPException(400, detail="max_speed must be in [0.01, 0.25] m/s")
    node().core.config.max_speed = body.max_speed
    return {"max_speed": body.max_speed}


@router.post("/target")
def target(body: TargetBody):
    n = node()
    if body.u is not None and body.v is not None:
        xy = n.unproject(body.u, body.v, n.tip_z())
        if xy is None:
            raise HTTPException(503, detail="camera model unavailable (TF or camera_info missing)")
    elif body.x is not None and body.y is not None:
        xy = (body.x, body.y)
    else:
        raise HTTPException(400, detail="give u, v or x, y")
    n.set_ui_target(*xy)
    return {"x": xy[0], "y": xy[1]}


@router.post("/park")
def park():
    """MoveIt (joint-space) move to the first home point, tool vertical, lifted above push height."""
    n = node()
    if n.enabled:
        raise HTTPException(409, detail="disable the guard first (MoveIt and the guard both move the arm)")
    home = n.task.home_candidates[0]
    rpy = n.cfg.get("task", {}).get("park_rpy", [3.1416, 0.0, -3.1416])
    req = MovePose.Request()
    req.pos = [float(home[0]), float(home[1]), float(n.task.push_z + n.lift_height)]
    req.ori = [float(v) for v in rpy]
    resp = rn.call_service(rn.require_node().cli_abs_base_joint, req, timeout=60)
    return {"success": resp.success, "message": resp.message, "pos": list(req.pos), "ori": list(req.ori)}


# ----------------------------------------------------------------------- camera setup

@router.get("/camera")
def camera():
    info = node().camera_info_dict()
    if info is None:
        raise HTTPException(404, detail="no ROI yet (waiting for a camera frame and TF)")
    return info


@router.post("/camera/roi")
def camera_roi(body: RoiBody):
    try:
        return node().set_roi(tuple(body.roi) if body.roi else None)
    except ValueError as exc:
        _bad(exc)


@router.post("/camera/threshold")
def camera_threshold(body: ThresholdBody):
    try:
        return node().set_threshold(body.model_dump())
    except (ValueError, KeyError) as exc:
        _bad(exc)


@router.post("/camera/pick")
def camera_pick(body: PickBody):
    """Set the T colour from the pixel the operator clicked on the T."""
    try:
        return node().pick_color(body.u, body.v)
    except ValueError as exc:
        _bad(exc)


@router.get("/feedback.png")
def feedback(mode: Optional[str] = None):
    try:
        data = node().feedback_png(mode)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    if data is None:
        raise HTTPException(503, detail="no fresh frame or no ROI yet")
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/feedback")
def set_feedback(body: FeedbackBody):
    try:
        node().set_feedback(body.mode)
    except ValueError as exc:
        _bad(exc)
    return {"feedback": body.mode}


# ------------------------------------------------------------------------- sessions

@router.post("/session/start")
def session_start(body: SessionBody):
    try:
        node().start_session(body.dataset, body.operator, body.n_episodes, body.input_device,
                             body.episode_seconds, body.start_from_home, body.wait_before_record)
    except ValueError as exc:
        _bad(exc)
    return {"result": "started"}


@router.post("/session/{cmd}")
def session_cmd(cmd: str):
    try:
        node().command(cmd)
    except ValueError as exc:
        _bad(exc)
    return {"result": cmd}


# ------------------------------------------------------------------------- datasets

def _store(name: str) -> ic.RawStore:
    if "/" in name or name.startswith(".") or name == "calibration":
        raise HTTPException(400, detail="bad dataset name")
    return ic.RawStore(inode.DATA / name)


@router.get("/datasets")
def datasets():
    out = []
    if inode.DATA.exists():
        for d in sorted(inode.DATA.iterdir()):
            if d.is_dir() and (d / ic.SIDECAR).exists():
                eps = ic.RawStore(d).episodes()
                out.append({"name": d.name, "episodes": len(eps),
                            "frames": sum(e.get("n_frames", 0) for e in eps),
                            "seconds": round(sum(e.get("n_frames", 0) / e.get("fps", 10) for e in eps), 1)})
    return out


@router.get("/datasets/{name}/episodes")
def episodes(name: str):
    return _store(name).episodes()


@router.delete("/datasets/{name}/episodes/last")
def delete_last(name: str):
    n = rn.imitation_node
    if n is not None and (n.recording or n.saving):
        raise HTTPException(409, detail="busy recording or saving")
    removed = _store(name).delete_last()
    if removed is None:
        raise HTTPException(404, detail="no episodes")
    return removed


def _load_episode(name: str, raw_index: int):
    path = inode.DATA / name / "raw" / f"episode_{raw_index:06d}.npz"
    if not path.exists():
        raise HTTPException(404, detail="episode not found")
    return np.load(path)


@router.get("/datasets/{name}/episodes/{raw_index}/series")
def episode_series(name: str, raw_index: int):
    """State and action per frame (sheet frame, metres), for the review plot."""
    z = _load_episode(name, raw_index)
    return {
        "n": int(z["action"].shape[0]),
        "state": np.round(z["observation__state"].astype(float), 5).tolist(),
        "action": np.round(z["action"].astype(float), 5).tolist(),
    }


@router.get("/datasets/{name}/episodes/{raw_index}/frame/{k}.png")
def episode_frame(name: str, raw_index: int, k: int):
    z = _load_episode(name, raw_index)
    imgs = z["observation__images__top"]
    if not 0 <= k < imgs.shape[0]:
        raise HTTPException(404, detail="frame out of range")
    return Response(cv2.imencode(".png", cv2.cvtColor(imgs[k], cv2.COLOR_RGB2BGR))[1].tobytes(),
                    media_type="image/png")


# ------------------------------------------------------------------------- commands

@router.get("/commands")
def commands(dataset: str = "pusht_cr3a_sim"):
    """Host-side commands for converting and running a policy, with this setup's paths."""
    host_data = os.environ.get("PUSHT_HOST_DATA_DIR", "~/workspaces/movensys-intelligence/movensys_push_t/datasets")
    mode = node().mode
    domain = os.environ.get("ROS_DOMAIN_ID", "0")
    sim = "true" if mode == "sim" else "false"
    return {
        "convert": (
            "cd ~/movensys-imitation && source env.bash\n"
            f"python ~/workspaces/movensys-intelligence/movensys_push_t/scripts/to_lerobot.py "
            f"{host_data}/{dataset} --repo-id movensys/{dataset} "
            f"--root datasets/movensys/{dataset}"),
        "train": (
            "cd ~/movensys-imitation && source env.bash\n"
            "movensys-train --config_path=movensys_imitation/configs/diffusion.yaml,"
            "movensys_imitation/configs/pusht_sim.yaml \\\n"
            f"    --dataset.repo_id=movensys/{dataset} --dataset.root=datasets/movensys/{dataset} \\\n"
            f"    --seed=1 --output_dir=outputs/sim/diffusion_{dataset}_s1"),
        "policy_runner": (
            f"cd ~/movensys-imitation && source env.bash && export ROS_DOMAIN_ID={domain}\n"
            "python -m movensys_imitation_ros.policy_runner --ros-args \\\n"
            f"    -p use_sim_time:={sim} -p mode:={mode} -p run_mode:=slow \\\n"
            f"    -p image_topic:=/pusht/feedback_image -p calibration_dir:={host_data}/calibration/{mode}_feedback \\\n"
            f"    -p pretrained:=outputs/sim/diffusion_{dataset}_s1/checkpoints/last/pretrained_model \\\n"
            "    -p policy_overrides:=\"--policy.noise_scheduler_type=DDIM --policy.num_inference_steps=10\" \\\n"
            "    --params-file movensys_imitation_ros/config/dobot_cr3a/task.yaml \\\n"
            "    --params-file movensys_imitation_ros/config/dobot_cr3a/runner.yaml"),
        "notes": [
            "Start the policy runner first, then a session with input 'policy': the runner acts only "
            "while /episode_recorder/state is recording:<n>, and a policy episode always runs the "
            "full episode duration.",
            "The runner reads /pusht/feedback_image, the same ROI image (bw / gray / rgb) the "
            "recorder stores, so keep the feedback mode the policy was trained with.",
        ],
    }
