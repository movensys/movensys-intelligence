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
from pydantic import BaseModel

import ros2_node as rn
from scripts import imitation_core as ic
from scripts import imitation_node as inode

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


class RoiBody(BaseModel):
    roi: Optional[List[int]] = None   # [x0, y0, w, h] in the camera frame; None: auto (push area)


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


# ----------------------------------------------------------------------- camera setup

@router.post("/camera/roi")
def camera_roi(body: RoiBody):
    try:
        return node().set_roi(tuple(body.roi) if body.roi else None)
    except ValueError as exc:
        _bad(exc)


@router.get("/policy_image.png")
def policy_image():
    """The grayscale 256 x 256 ROI image of the newest frame: what is recorded and fed to the policy."""
    data = node().policy_png()
    if data is None:
        raise HTTPException(503, detail="no fresh frame or no ROI yet")
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


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
    if "/" in name or name.startswith(".") or name in ("calibration", "lerobot"):
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
    """Host-side commands (movensys_push_t venv) for keyboard_teleop, converting, training and running a policy."""
    mode = node().mode
    sim = "true" if mode == "sim" else "false"
    return {
        "keyboard_teleop": (
            f"mros ros2 run movensys_manipulator_moveit_config keyboard_teleop --ros-args -p use_sim_time:={sim} \\\n"
            "    -r /servo_node/pose_target_cmds:=/pusht/teleop_target \\\n"
            "    -r /servo_node/delta_twist_cmds:=/pusht/kb_unused_twist \\\n"
            "    -r /servo_node/delta_joint_cmds:=/pusht/kb_unused_joint \\\n"
            "    -r /servo_node/switch_command_type:=/pusht/kb_unused_switch"),
        "convert": (
            "source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash\n"
            f"pusht-to-lerobot {dataset}"),
        "train": (
            "source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash\n"
            "pusht-train --config_path=learning/configs/diffusion.yaml,learning/configs/train_pusht.yaml \\\n"
            f"    --dataset.repo_id=movensys/{dataset} --dataset.root=datasets/lerobot/{dataset} \\\n"
            f"    --seed=1 --output_dir=outputs/diffusion_{dataset}_s1"),
        "policy_runner": (
            "source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash\n"
            f"pusht-policy-runner --ros-args -p use_sim_time:={sim} -p run_mode:=slow \\\n"
            f"    -p pretrained:=outputs/diffusion_{dataset}_s1/checkpoints/last/pretrained_model \\\n"
            "    -p policy_overrides:=\"--policy.noise_scheduler_type=DDIM --policy.num_inference_steps=10\""),
        "notes": [
            "Start the policy runner first, then a session with input 'policy': the runner acts only "
            "while /episode_recorder/state is recording:<n>, and a policy episode always runs the "
            "full episode duration.",
            "keyboard_teleop (/pusht/teleop_target) and the policy (/pusht/target_raw) use separate "
            "topics; the guard listens to the one that owns the arm. Full procedure: doc/train.md, doc/inference.md.",
        ],
    }
