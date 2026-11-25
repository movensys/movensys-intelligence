"""PushT imitation-learning logic without ROS: guard, camera ROI, feedback image, episode buffer.

Ported from movensys-imitation (origin/devel, 2026-11-22) so data collected here trains with that
repository unchanged:

* :class:`GuardCore` is ``movensys_imitation_ros/guard_core.py`` (planar target, area clamp, step
  limit, EEF-distance limit, stick or absolute-pose source).
* :class:`EpisodeBuffer` builds frames of the recorder schema
  (``movensys_imitation.data.convert_gym_pusht.recorder_features``): ``observation.state`` and
  ``action`` in the sheet frame (planning frame minus the push-area centre), the ROI image at
  256 x 256 and the joints. ``block_pose``, ``coverage`` and ``iou`` are NaN: this setup records
  demonstrations like video clips and does not score them.
* :class:`CameraSetup` is saved as ``calibration.yaml`` with the ``image_size`` / ``crop`` keys
  that movensys-imitation's ``policy_runner`` reads.

The ROI image ("feedback") is black and white by default: the T, found by an HSV range, white on
black. ``gray`` and ``rgb`` are kept as options.
"""

from __future__ import annotations

import datetime
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

SHEET_SIZE = (0.60, 0.30)
TASK = "Push the T-shaped block onto the T-shaped target."
JOINT_NAMES = tuple(f"joint{i}" for i in range(1, 7))

CALIBRATION_YAML = "calibration.yaml"
SIDECAR = "movensys_episodes.jsonl"


@dataclass
class TaskConfig:
    planning_frame: str = "world_manipulator"
    eef_frame: str = "Link6"
    area_center: tuple[float, float] = (-0.03, -0.05)
    area_size: tuple[float, float] = SHEET_SIZE
    table_z: float = 0.0431
    link6_to_tip_bottom: float = 0.22
    tip_clearance_nominal: float = 0.010
    home_candidates: tuple[tuple[float, float], ...] = ((-0.03, 0.08), (-0.25, 0.08), (0.19, 0.08))

    @property
    def push_z(self) -> float:
        """Link6 z with the tip ``tip_clearance_nominal`` above the table."""
        return self.table_z + self.link6_to_tip_bottom + self.tip_clearance_nominal


# ----------------------------------------------------------------------------------- guard

EPS = 1e-9
STATE_INIT, STATE_FAULT, STATE_HOLD, STATE_MOVING = "init", "fault", "hold", "moving"
SOURCE_STICK, SOURCE_POSE = "stick", "pose"
SOURCES = (SOURCE_STICK, SOURCE_POSE)


@dataclass
class GuardConfig:
    area_center: tuple[float, float] = (-0.03, -0.05)
    area_size: tuple[float, float] = SHEET_SIZE
    step_limit: float = 0.005
    eef_distance_limit: float = 0.030
    max_speed: float = 0.12
    deadzone: float = 0.05
    expo: float = 1.5
    joy_stale: float = 0.2
    eef_stale: float = 0.5
    pose_stale: float = 0.5

    @property
    def area_min(self) -> tuple[float, float]:
        return (self.area_center[0] - self.area_size[0] / 2, self.area_center[1] - self.area_size[1] / 2)

    @property
    def area_max(self) -> tuple[float, float]:
        return (self.area_center[0] + self.area_size[0] / 2, self.area_center[1] + self.area_size[1] / 2)


@dataclass
class GuardInputs:
    dt: float
    eef_xy: tuple[float, float] | None
    eef_age: float = 0.0
    servo_halted: bool = False
    deadman: bool = True
    stick: tuple[float, float] | None = None  # already in the planning frame, -1..1
    joy_age: float = 0.0
    pose_cmd: tuple[float, float] | None = None
    pose_age: float = 0.0


@dataclass
class GuardOutput:
    publish: bool
    target: tuple[float, float] | None
    state: str
    reason: str = ""


class GuardCore:
    """Guarded planar target (movensys_imitation_ros.guard_core.GuardCore)."""

    def __init__(self, config: GuardConfig | None = None, source: str = SOURCE_STICK):
        self.config = config or GuardConfig()
        self.source = source
        self.target: tuple[float, float] | None = None
        self.state = STATE_INIT
        self.reason = ""

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        lo, hi = self.config.area_min, self.config.area_max
        return (min(max(x, lo[0]), hi[0]), min(max(y, lo[1]), hi[1]))

    def inside(self, x: float, y: float, margin: float = 0.0) -> bool:
        cx, cy = self.clamp(x, y)
        return math.hypot(cx - x, cy - y) <= margin

    def stick_to_velocity(self, sx: float, sy: float) -> tuple[float, float]:
        c = self.config
        m = math.hypot(sx, sy)
        if m <= c.deadzone or m == 0.0:
            return (0.0, 0.0)
        gain = min((m - c.deadzone) / (1.0 - c.deadzone), 1.0) ** c.expo
        return (sx / m * gain * c.max_speed, sy / m * gain * c.max_speed)

    def limit_step(self, current, desired) -> tuple[float, float]:
        dx, dy = desired[0] - current[0], desired[1] - current[1]
        n = math.hypot(dx, dy)
        if n <= self.config.step_limit or n == 0.0:
            return (float(desired[0]), float(desired[1]))
        k = self.config.step_limit / n
        return (current[0] + dx * k, current[1] + dy * k)

    def ramp(self, current: float, goal: float) -> float:
        d = goal - current
        if abs(d) <= self.config.step_limit:
            return goal
        return current + math.copysign(self.config.step_limit, d)

    def reset(self) -> None:
        self.target = None
        self.state = STATE_INIT

    def set_source(self, source: str) -> None:
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")
        self.source = source

    def update(self, inp: GuardInputs) -> GuardOutput:
        c = self.config
        if inp.eef_xy is None or inp.eef_age > c.eef_stale:
            return self._out(False, STATE_FAULT, "eef_stale")
        eef = inp.eef_xy
        if self.target is None:
            if not self.inside(*eef, margin=c.eef_distance_limit):
                return self._out(False, STATE_FAULT, "eef_outside_area")
            self.target = self.clamp(*eef)
        if inp.servo_halted:
            self.target = self.clamp(*eef)
            return self._out(True, STATE_HOLD, "servo_halted")
        desired, reason = self._desired(inp)
        if desired is None:
            return self._out(True, STATE_HOLD, reason)
        new = self.limit_step(self.target, self.clamp(*desired))
        if math.hypot(new[0] - eef[0], new[1] - eef[1]) > c.eef_distance_limit + EPS:
            return self._out(True, STATE_HOLD, "eef_distance")
        moved = math.hypot(new[0] - self.target[0], new[1] - self.target[1]) > EPS
        self.target = new
        return self._out(True, STATE_MOVING if moved else STATE_HOLD, "" if moved else reason)

    def _desired(self, inp: GuardInputs):
        c = self.config
        if not inp.deadman:
            return None, "deadman"
        if self.source == SOURCE_STICK:
            if inp.stick is None or inp.joy_age > c.joy_stale:
                return None, "joy_stale"
            vx, vy = self.stick_to_velocity(*inp.stick)
            if vx == 0.0 and vy == 0.0:
                return None, "stick_centred"
            return (self.target[0] + vx * inp.dt, self.target[1] + vy * inp.dt), ""
        if inp.pose_cmd is None or inp.pose_age > c.pose_stale:
            return None, "pose_stale"
        return inp.pose_cmd, "at_target"

    def _out(self, publish: bool, state: str, reason: str) -> GuardOutput:
        self.state, self.reason = state, reason
        return GuardOutput(publish, self.target, state, reason)


# ---------------------------------------------------------------------------- camera setup

@dataclass
class HsvRange:
    """Inclusive HSV box, OpenCV scale (H 0..179); selects the T for the black-and-white image."""

    hue: tuple[int, int] = (40, 90)
    sat_min: int = 80
    val: tuple[int, int] = (20, 245)

    def mask(self, hsv: np.ndarray) -> np.ndarray:
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        lo, hi = self.hue
        in_hue = (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)
        return in_hue & (s >= self.sat_min) & (v >= self.val[0]) & (v <= self.val[1])

    def to_dict(self) -> dict:
        return {"hue": [int(x) for x in self.hue], "sat_min": int(self.sat_min), "val": [int(x) for x in self.val]}

    @classmethod
    def from_dict(cls, d: dict) -> "HsvRange":
        return cls(tuple(int(x) for x in d["hue"]), int(d["sat_min"]), tuple(int(x) for x in d["val"]))


def largest_component(raw: np.ndarray, open_px: int = 3) -> np.ndarray:
    """Open ``raw`` (bool) and keep the largest 8-connected component."""
    m = raw.astype(np.uint8)
    if open_px > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_px, open_px))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return np.zeros(raw.shape, bool)
    i = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    return labels == i


@dataclass
class CameraSetup:
    """ROI of the top camera and the T colour range, saved as ``calibration.yaml``.

    ``image_size`` and ``crop`` are the keys movensys-imitation's ``load_image_crop`` reads, so
    the policy runner can take its crop from this file.
    """

    image_size: tuple[int, int]
    crop: tuple[int, int, int, int]          # ROI (x0, y0, w, h) in the full frame
    threshold: HsvRange = field(default_factory=HsvRange)
    meta: dict = field(default_factory=dict)

    def apply_crop(self, frame: np.ndarray) -> np.ndarray:
        x0, y0, w, h = self.crop
        return frame[y0:y0 + h, x0:x0 + w]

    def check_frame(self, frame: np.ndarray) -> None:
        if frame.shape[1::-1] != tuple(self.image_size):
            raise ValueError(f"frame is {frame.shape[1]} x {frame.shape[0]}, ROI was set on "
                             f"{self.image_size[0]} x {self.image_size[1]}")

    @staticmethod
    def clamp_roi(roi, image_size) -> tuple[int, int, int, int]:
        w, h = image_size
        x0, y0, cw, ch = (int(round(v)) for v in roi)
        x0, y0 = max(0, min(x0, w - 32)), max(0, min(y0, h - 32))
        return (x0, y0, max(32, min(cw, w - x0)), max(32, min(ch, h - y0)))

    def save(self, directory: Path) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        (d / CALIBRATION_YAML).write_text(yaml.safe_dump({
            "image_size": list(self.image_size), "crop": list(self.crop),
            "threshold": self.threshold.to_dict(),
            "meta": {"updated": datetime.datetime.now().isoformat(timespec="seconds"), **self.meta},
        }, sort_keys=False))

    @classmethod
    def load(cls, directory: Path) -> "CameraSetup":
        doc = yaml.safe_load((Path(directory) / CALIBRATION_YAML).read_text())
        return cls(tuple(int(x) for x in doc["image_size"]), tuple(int(x) for x in doc["crop"]),
                   HsvRange.from_dict(doc["threshold"]) if doc.get("threshold") else HsvRange(),
                   dict(doc.get("meta") or {}))


def decode_image(data, width: int, height: int, step: int, encoding: str) -> np.ndarray:
    """sensor_msgs/Image -> RGB uint8 (H, W, 3), numpy only."""
    rows = np.frombuffer(bytes(data), dtype=np.uint8).reshape(height, step)
    if encoding in ("rgb8", "bgr8"):
        arr = rows[:, :width * 3].reshape(height, width, 3)
        if encoding == "bgr8":
            arr = arr[..., ::-1]
    elif encoding in ("rgba8", "bgra8"):
        arr = rows[:, :width * 4].reshape(height, width, 4)[..., :3]
        if encoding == "bgra8":
            arr = arr[..., ::-1]
    else:
        raise ValueError(f"unsupported image encoding {encoding!r}")
    return np.ascontiguousarray(arr)


# -------------------------------------------------------------------------- episode buffer

@dataclass
class Sample:
    t: float
    image: np.ndarray | None = None
    image_t: float = -math.inf
    eef_xy: tuple[float, float] | None = None
    action_xy: tuple[float, float] | None = None
    joints: tuple[float, ...] | None = None


@dataclass
class Timing:
    n_frames: int = 0
    missed_ticks: int = 0
    max_tick_dt: float = 0.0
    stale_frames: int = 0
    max_image_age: float = 0.0

    def ok(self) -> bool:
        return self.missed_ticks == 0 and self.stale_frames == 0

    def to_dict(self, fps: int) -> dict:
        return {
            "n_frames": self.n_frames, "missed_ticks": self.missed_ticks,
            "max_tick_dt": round(self.max_tick_dt, 4), "stale_frames": self.stale_frames,
            "max_image_age": round(self.max_image_age, 4), "timing_ok": self.ok(),
            "seconds": round(self.n_frames / fps, 2),
        }


class EpisodeBuffer:
    """Frames of the recorder schema for one episode, kept as arrays."""

    def __init__(self, cal: CameraSetup, fps: int = 10, image_size: int = 256,
                 sheet_origin=(-0.03, -0.05), max_image_age: float = 0.15,
                 tick_tolerance: float = 0.02, feedback: str = "bw"):
        self.cal, self.fps, self.image_size = cal, fps, image_size
        self.feedback = feedback
        self.sheet_origin = sheet_origin
        self.max_image_age, self.tick_tolerance = max_image_age, tick_tolerance
        self.images: list[np.ndarray] = []
        self.state: list[tuple[float, float]] = []
        self.action: list[tuple[float, float]] = []
        self.joints: list[tuple[float, ...]] = []
        self.timing = Timing()
        self.last_t: float | None = None

    def __len__(self) -> int:
        return len(self.images)

    def add(self, s: Sample) -> None:
        missing = [n for n in ("image", "eef_xy", "action_xy", "joints") if getattr(s, n) is None]
        if missing:
            raise ValueError("missing " + ", ".join(missing))
        tm, period = self.timing, 1.0 / self.fps
        if self.last_t is not None:
            dt = s.t - self.last_t
            tm.max_tick_dt = max(tm.max_tick_dt, dt)
            if dt > period + self.tick_tolerance:
                tm.missed_ticks += max(1, int(round(dt / period)) - 1)
        self.last_t = s.t
        age = s.t - s.image_t
        tm.max_image_age = max(tm.max_image_age, age)
        if age > self.max_image_age:
            tm.stale_frames += 1
        self.cal.check_frame(s.image)
        crop = feedback_image(self.cal.apply_crop(s.image), self.feedback, self.cal.threshold,
                              self.image_size)
        ox, oy = self.sheet_origin
        self.images.append(np.ascontiguousarray(crop))
        self.state.append((s.eef_xy[0] - ox, s.eef_xy[1] - oy))
        self.action.append((s.action_xy[0] - ox, s.action_xy[1] - oy))
        self.joints.append(tuple(s.joints))
        tm.n_frames = len(self.images)

    def arrays(self) -> dict:
        n = len(self)
        return {
            "observation.images.top": np.stack(self.images).astype(np.uint8),
            "observation.state": np.asarray(self.state, np.float32).reshape(n, 2),
            "action": np.asarray(self.action, np.float32).reshape(n, 2),
            "observation.joints": np.asarray(self.joints, np.float32).reshape(n, 6),
            "block_pose": np.full((n, 3), np.nan, np.float32),
            # Not scored in this setup; kept (NaN) so the movensys-imitation schema is unchanged.
            "coverage": np.full((n, 1), np.nan, np.float32),
            "iou": np.full((n, 1), np.nan, np.float32),
        }


class RawStore:
    """Episodes as ``<root>/raw/episode_NNNNNN.npz`` plus the imitation sidecar.

    ``scripts/to_lerobot.py`` (movensys-imitation venv) turns them into a LeRobot dataset; the
    sidecar lines get their LeRobot ``episode_index`` there.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.raw = self.root / "raw"
        self.sidecar = self.root / SIDECAR

    def episodes(self) -> list[dict]:
        if not self.sidecar.exists():
            return []
        return [json.loads(x) for x in self.sidecar.read_text().splitlines() if x.strip()]

    def next_index(self) -> int:
        eps = self.episodes()
        return max((e["raw_index"] for e in eps), default=-1) + 1

    def save(self, buf: EpisodeBuffer, meta: dict, cal_dir: Path | None = None) -> dict:
        if len(buf) == 0:
            raise ValueError("empty episode")
        self.raw.mkdir(parents=True, exist_ok=True)
        idx = self.next_index()
        path = self.raw / f"episode_{idx:06d}.npz"
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **{k.replace(".", "__"): v for k, v in buf.arrays().items()})
        os.replace(tmp, path)
        if cal_dir is not None and not (self.root / "calibration" / CALIBRATION_YAML).exists():
            dst = self.root / "calibration"
            dst.mkdir(exist_ok=True)
            (dst / CALIBRATION_YAML).write_bytes((Path(cal_dir) / CALIBRATION_YAML).read_bytes())
        line = {
            "raw_index": idx,
            "file": f"raw/{path.name}",
            "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "fps": buf.fps,
            "task": TASK,
            "feedback": buf.feedback,
            "roi": [int(v) for v in buf.cal.crop],
            "sheet_origin_wm": [float(v) for v in buf.sheet_origin],
            **buf.timing.to_dict(buf.fps),
            "versions": {"numpy": np.__version__, "source": "movensys_push_t"},
            **meta,
        }
        with self.sidecar.open("a") as f:
            f.write(json.dumps(line) + "\n")
        return line

    def delete_last(self) -> dict | None:
        eps = self.episodes()
        if not eps:
            return None
        last = eps[-1]
        (self.root / last["file"]).unlink(missing_ok=True)
        self.sidecar.write_text("".join(json.dumps(e) + "\n" for e in eps[:-1]))
        return last


# --------------------------------------------------------------------- frame buffer and ROI

class FrameBuffer:
    """Thread-safe ring buffer of the newest camera frames.

    The ROS callback only stores the raw frame (no decoding, no JPEG) and never waits for a
    consumer; consumers take the newest entry and its age, so a slow consumer skips frames
    instead of working through a backlog of old ones.
    """

    def __init__(self, size: int = 4):
        import collections
        import threading

        self._buf = collections.deque(maxlen=size)
        self._lock = threading.Lock()
        self.seq = 0

    def put(self, image: np.ndarray, t_arrival: float, stamp: float = math.nan) -> int:
        with self._lock:
            self.seq += 1
            self._buf.append((self.seq, t_arrival, stamp, image))
            return self.seq

    def latest(self):
        """``(seq, arrival_time, header_stamp, image)`` of the newest frame, or None."""
        with self._lock:
            return self._buf[-1] if self._buf else None

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


FEEDBACK_MODES = ("bw", "gray", "rgb")


def feedback_image(crop_rgb: np.ndarray, mode: str, threshold: HsvRange | None,
                   size: int = 256, open_px: int = 3) -> np.ndarray:  # noqa: C901
    """Policy / dataset image of the ROI: ``bw`` = T white on black, ``gray`` or ``rgb``.

    Always (size, size, 3) uint8, so the LeRobot schema of movensys-imitation is unchanged.
    The binary mask is computed at full ROI resolution, then resized with area interpolation
    (edges stay anti-aliased, which keeps sub-pixel position information).
    """
    if mode == "bw":
        if threshold is None:
            raise ValueError("bw feedback needs a calibrated threshold")
        hsv = cv2.cvtColor(np.ascontiguousarray(crop_rgb), cv2.COLOR_RGB2HSV)
        mask = largest_component(threshold.mask(hsv), open_px)
        img = mask.astype(np.uint8) * 255
    elif mode == "gray":
        img = cv2.cvtColor(np.ascontiguousarray(crop_rgb), cv2.COLOR_RGB2GRAY)
    elif mode == "rgb":
        img = crop_rgb
    else:
        raise ValueError(f"feedback mode must be one of {FEEDBACK_MODES}")
    if img.shape[0] != size or img.shape[1] != size:
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    if img.ndim == 2:
        img = np.repeat(img[..., None], 3, axis=2)
    return np.ascontiguousarray(img)
