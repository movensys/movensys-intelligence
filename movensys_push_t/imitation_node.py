"""ROS 2 side of the PushT imitation features: planar guard, camera ROI, recorder, episode runner.

One node, ``movensys_push_t_imitation``, in the same executor as ``ros2_node.PushTNode``. It speaks
the topic interface of movensys-imitation, so that repository's ``policy_runner`` (venv) drives
this scene unchanged:

    in   /pusht/target_raw         geometry_msgs/PoseStamped  absolute target (policy)
    in   /pusht/waypoints          nav_msgs/Path              timed targets (replay)
    out  /servo_node/pose_target_cmds, /pusht/target_guarded  50 Hz while the guard is enabled
    out  /pusht/feedback_image     sensor_msgs/Image          the ROI image the recorder stores
                                                              (bw / gray / rgb, 256 x 256), 10 Hz
    out  /episode_recorder/state   std_msgs/String            idle | recording:<n>
    out  /planar_guard/state       std_msgs/String            <state>:<reason>
    out  /episode_manager/state    std_msgs/String            idle | reset:* | record:<n> | end:* | fault:*

Episodes are demonstrations recorded like video clips: the operator moves the T and stops the
recording (or it ends after ``episode_seconds``); a policy episode always runs the full
``episode_seconds``. Nothing is scored.

Camera frames come from ``ros2_node.frames`` (a ring buffer filled by the only image
subscription); every consumer takes the newest frame, so nothing works on an old image.
Parameters: ``config/imitation.yaml``.
"""

from __future__ import annotations

import math
import os
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import yaml
from geometry_msgs.msg import PoseStamped
from moveit_msgs.msg import ServoStatus
from moveit_msgs.srv import ServoCommandType
from nav_msgs.msg import Path as PathMsg
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import Bool, String
import tf2_ros

import imitation_core as ic

APP = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("PUSHT_IMITATION_CONFIG", APP / "config" / "imitation.yaml"))
DATA = Path(os.environ.get("PUSHT_DATA_DIR", APP / "datasets"))
CAMERA_FRAME = "camera_top_color_optical_frame"
SERVO_HALT = (ServoStatus.HALT_FOR_SINGULARITY, ServoStatus.HALT_FOR_COLLISION, ServoStatus.JOINT_BOUND)


def _chown_like(path: Path, ref: Path) -> None:
    """Give files written as root in the container the owner of the mounted data directory."""
    try:
        st = ref.stat()
        for p in [path, *path.rglob("*")] if path.is_dir() else [path]:
            os.chown(p, st.st_uid, st.st_gid)
    except OSError:
        pass


class ManagerAbort(Exception):
    pass


class ImitationNode(Node):
    def __init__(self, frames: ic.FrameBuffer, camera_info_getter):
        use_sim = os.environ.get("PUSHT_USE_SIM_TIME", "true").lower() in ("1", "true", "yes")
        super().__init__("movensys_push_t_imitation",
                         parameter_overrides=[Parameter("use_sim_time", value=use_sim)])
        cfg = yaml.safe_load(CONFIG.read_text()) if CONFIG.exists() else {}
        self.cfg = cfg
        self.mode = os.environ.get("PUSHT_MODE", cfg.get("mode", "sim"))
        t = cfg.get("task", {})
        self.task = ic.TaskConfig(
            area_center=tuple(t.get("area_center", (-0.03, -0.05))),
            area_size=tuple(t.get("area_size", ic.SHEET_SIZE)),
            table_z=t.get("table_z", 0.0431),
            link6_to_tip_bottom=t.get("link6_to_tip_bottom", 0.22),
            tip_clearance_nominal=t.get("tip_clearance_nominal", 0.010),
            home_candidates=tuple(tuple(c) for c in t.get("home_candidates", ic.TaskConfig.home_candidates)),
        )
        g = cfg.get("guard", {})
        self.core = ic.GuardCore(ic.GuardConfig(
            area_center=self.task.area_center, area_size=self.task.area_size,
            step_limit=g.get("step_limit", 0.005), eef_distance_limit=g.get("eef_distance_limit", 0.03),
            max_speed=g.get("max_speed", 0.12), deadzone=g.get("deadzone", 0.05), expo=g.get("expo", 1.5),
            joy_stale=g.get("joy_stale", 0.2), eef_stale=g.get("eef_stale", 0.5),
            pose_stale=g.get("pose_stale", 0.5)))
        self.guard_hz = float(g.get("stream_hz", 50.0))
        self.latch_mode = g.get("latch_mode", "nominal" if self.mode == "sim" else "measured")
        self.lift_height = float(g.get("lift_height", 0.08))
        c = cfg.get("camera", {})
        self.image_stale = float(c.get("image_stale", 0.5))
        self.roi_margin = float(c.get("roi_margin", 0.03))
        self.default_threshold = ic.HsvRange.from_dict(c["threshold"]) if c.get("threshold") else ic.HsvRange()
        r = cfg.get("recorder", {})
        self.rec_cfg = {"fps": int(r.get("fps", 10)), "image_size": int(r.get("image_size", 256)),
                        "max_image_age": float(r.get("max_image_age", 0.15)),
                        "tick_tolerance": float(r.get("tick_tolerance", 0.02))}
        self.feedback = r.get("feedback", "bw")
        m = cfg.get("episodes", {})
        self.ep_cfg = {
            "episode_seconds": float(m.get("episode_seconds", 30.0)),
            "home_tolerance": float(m.get("home_tolerance", 0.008)),
            "home_timeout": float(m.get("home_timeout", 30.0)),
            "lift_timeout": float(m.get("lift_timeout", 10.0)),
            "lower_settle": float(m.get("lower_settle", 0.5)),
        }

        self.frames = frames
        self.camera_info = camera_info_getter
        self.lock = threading.RLock()

        # guard
        self.enabled = False
        self.owner = "ui"              # ui | manager | policy: who may set targets
        self.eef: Optional[tuple[float, float, float]] = None
        self.eef_q: Optional[tuple[float, float, float, float]] = None
        self.eef_rx = -math.inf
        self.joints: Optional[tuple[float, ...]] = None
        self.servo_halted = False
        self.servo_msg = ""
        self.exec_active = False
        self.pose_mode_ok = False
        self.latched_z: Optional[float] = None
        self.latched_q: Optional[tuple[float, float, float, float]] = None
        self.lift_goal = 0.0
        self.lift_offset = 0.0
        self.stick = (0.0, 0.0)
        self.stick_deadman = False
        self.stick_rx = -math.inf
        self.pose_cmd: Optional[tuple[float, float]] = None
        self.pose_rx = -math.inf
        self.path: list[tuple[float, float, float]] = []
        self.guard_state = "disabled"
        self.last_guard_state = ""

        # camera setup (ROI + T colour), recorder, episode runner
        self.cam_dir = DATA / "calibration" / self.mode
        self.cam: Optional[ic.CameraSetup] = None
        try:
            self.cam = ic.CameraSetup.load(self.cam_dir)
        except (FileNotFoundError, KeyError, OSError):
            pass
        self.buffer: Optional[ic.EpisodeBuffer] = None
        self.recording = False
        self.rec_state = "idle"
        self.rec_error = ""
        self.man_state = "idle"
        self.man_note = ""
        self.man_cmd: Optional[str] = None
        self.man_thread: Optional[threading.Thread] = None
        self.session: dict = {}
        self.episode_t0: Optional[float] = None
        self.last_episode: Optional[dict] = None
        self.saving = False

        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        cb = ReentrantCallbackGroup()
        self.create_subscription(PoseStamped, "/wmx/moveit2/eef_pose", self._on_eef, 10, callback_group=cb)
        self.create_subscription(JointState, "/joint_states", self._on_joints, 10, callback_group=cb)
        self.create_subscription(ServoStatus, "/servo_node/status", self._on_servo_status, 10, callback_group=cb)
        self.create_subscription(Bool, "/moveit2_trajectory/execution_active", self._on_exec, latched, callback_group=cb)
        self.create_subscription(PoseStamped, "/pusht/target_raw", self._on_target_raw, 10, callback_group=cb)
        self.create_subscription(PathMsg, "/pusht/waypoints", self._on_waypoints, 10, callback_group=cb)
        self.servo_pub = self.create_publisher(PoseStamped, "/servo_node/pose_target_cmds", 10)
        self.guarded_pub = self.create_publisher(PoseStamped, "/pusht/target_guarded", 10)
        self.feedback_pub = self.create_publisher(Image, "/pusht/feedback_image", 1)
        self.rec_pub = self.create_publisher(String, "/episode_recorder/state", 10)
        self.guard_pub = self.create_publisher(String, "/planar_guard/state", 10)
        self.man_pub = self.create_publisher(String, "/episode_manager/state", 10)
        self.switch_client = self.create_client(ServoCommandType, "/servo_node/switch_command_type", callback_group=cb)
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.create_timer(1.0 / self.guard_hz, self._guard_tick, callback_group=MutuallyExclusiveCallbackGroup())
        self.create_timer(1.0 / self.rec_cfg["fps"], self._tick_10hz, callback_group=MutuallyExclusiveCallbackGroup())
        self.create_timer(1.0, self._heartbeat, callback_group=MutuallyExclusiveCallbackGroup())
        self.get_logger().info(f"imitation node up: mode {self.mode}, sim time {use_sim}, data {DATA}, "
                               f"ROI {'loaded' if self.cam else 'not set (auto on first frame)'}")

    # ------------------------------------------------------------------ time and callbacks
    def now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_eef(self, msg: PoseStamped) -> None:
        p, o = msg.pose.position, msg.pose.orientation
        self.eef, self.eef_q, self.eef_rx = (p.x, p.y, p.z), (o.x, o.y, o.z, o.w), time.monotonic()

    def _on_joints(self, msg: JointState) -> None:
        idx = {n: i for i, n in enumerate(msg.name)}
        if all(n in idx for n in ic.JOINT_NAMES):
            self.joints = tuple(msg.position[idx[n]] for n in ic.JOINT_NAMES)

    def _on_servo_status(self, msg: ServoStatus) -> None:
        self.servo_halted = msg.code in SERVO_HALT
        self.servo_msg = msg.message if self.servo_halted else ""

    def _on_exec(self, msg: Bool) -> None:
        with self.lock:
            was, self.exec_active = self.exec_active, bool(msg.data)
            if was != self.exec_active:
                self.core.reset()  # re-anchor on the measured pose once MoveIt is done

    def _on_target_raw(self, msg: PoseStamped) -> None:
        with self.lock:
            if self.owner != "policy" or msg.header.frame_id not in ("", self.task.planning_frame):
                return
            self.path = []
            self.pose_cmd, self.pose_rx = (msg.pose.position.x, msg.pose.position.y), time.monotonic()

    def _on_waypoints(self, msg: PathMsg) -> None:
        with self.lock:
            if self.owner != "policy":
                return
            self.path = sorted((Time.from_msg(p.header.stamp).nanoseconds * 1e-9,
                                p.pose.position.x, p.pose.position.y) for p in msg.poses)

    # ------------------------------------------------------------------------- guard
    def set_enabled(self, on: bool) -> str:
        with self.lock:
            if on == self.enabled:
                return "unchanged"
            if not on and self.man_thread and self.man_thread.is_alive():
                raise ValueError("abort the episode run first")
            self.enabled = on
            self.core.reset()
            self.latched_z = self.latched_q = None
            self.lift_goal = self.lift_offset = 0.0
            self.pose_mode_ok = False
            self.pose_cmd, self.path = None, []
        if on:
            self._switch_pose_mode()
        return "enabled" if on else "disabled"

    def _switch_pose_mode(self) -> None:
        if not self.switch_client.service_is_ready():
            return
        req = ServoCommandType.Request()
        req.command_type = ServoCommandType.Request.POSE

        def done(fut):
            try:
                self.pose_mode_ok = bool(fut.result().success)
            except Exception:  # noqa: BLE001
                self.pose_mode_ok = False
        self.switch_client.call_async(req).add_done_callback(done)

    def relatch(self) -> None:
        with self.lock:
            if self.lift_goal > 0 or abs(self.lift_offset) > 1e-4:
                raise ValueError("lower the tool before relatching")
            self.latched_z = self.latched_q = None

    def set_lift(self, up: bool) -> None:
        with self.lock:
            self.lift_goal = self.lift_height if up else 0.0

    def lift_state(self) -> str:
        if abs(self.lift_offset - self.lift_goal) > 1e-6:
            return "moving"
        return "up" if self.lift_goal > 1e-6 else "down"

    def set_stick(self, sx: float, sy: float, deadman: bool) -> None:
        """Stick in screen axes (right, up), -1..1, rotated onto the planning frame."""
        right, up = self.screen_axes()
        with self.lock:
            if self.owner != "ui":
                return
            self.core.set_source(ic.SOURCE_STICK)
            self.stick = (sx * right[0] + sy * up[0], sx * right[1] + sy * up[1])
            self.stick_deadman, self.stick_rx = bool(deadman), time.monotonic()

    def set_ui_target(self, x: float, y: float) -> None:
        with self.lock:
            if self.owner != "ui":
                return
            self.core.set_source(ic.SOURCE_POSE)
            self.path = []
            self.pose_cmd, self.pose_rx = (x, y), time.monotonic()

    def _pose_command(self):
        if self.path:
            now = self.now()
            first, last = self.path[0], self.path[-1]
            if now <= first[0]:
                return (first[1], first[2]), 0.0
            if now >= last[0]:
                return (last[1], last[2]), now - last[0]
            for (t0, x0, y0), (t1, x1, y1) in zip(self.path, self.path[1:]):
                if t0 <= now <= t1:
                    a = 0.0 if t1 == t0 else (now - t0) / (t1 - t0)
                    return (x0 + a * (x1 - x0), y0 + a * (y1 - y0)), 0.0
        if self.pose_cmd is None:
            return None, math.inf
        if self.owner == "manager":
            return self.pose_cmd, 0.0  # scripted targets never go stale
        return self.pose_cmd, time.monotonic() - self.pose_rx

    def _guard_tick(self) -> None:
        with self.lock:
            if not self.enabled:
                self._set_guard_state("disabled")
                return
            if self.exec_active:
                self._set_guard_state("hold:moveit_executing")
                return
            if not self.pose_mode_ok:
                self._switch_pose_mode()
            eef_age = time.monotonic() - self.eef_rx
            if self.eef is not None and self.latched_z is None and eef_age < self.core.config.eef_stale:
                measured = self.eef[2]
                self.latched_z = self.task.push_z if self.latch_mode == "nominal" else measured
                self.lift_offset = measured - self.latched_z
                self.latched_q = self.eef_q
                # Never lower onto the T by itself: a tool above the plane latches lifted and the
                # operator lowers it (Lower button) where the tip is clear.
                if self.lift_offset > 0.005:
                    self.lift_goal = min(self.lift_height, self.lift_offset)
            pose_cmd, pose_age = self._pose_command()
            stick_src = self.core.source == ic.SOURCE_STICK and self.owner == "ui"
            out = self.core.update(ic.GuardInputs(
                dt=1.0 / self.guard_hz,
                eef_xy=None if self.eef is None else self.eef[:2], eef_age=eef_age,
                servo_halted=self.servo_halted,
                deadman=self.stick_deadman if stick_src else True,
                stick=self.stick, joy_age=time.monotonic() - self.stick_rx,
                pose_cmd=pose_cmd, pose_age=pose_age))
            self._set_guard_state(f"{out.state}:{out.reason}" if out.reason else out.state)
            if not out.publish or out.target is None or self.latched_z is None:
                return
            self.lift_offset = self.core.ramp(self.lift_offset, self.lift_goal)
            msg = PoseStamped()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = self.task.planning_frame
            msg.pose.position.x, msg.pose.position.y = out.target
            msg.pose.position.z = self.latched_z + self.lift_offset
            (msg.pose.orientation.x, msg.pose.orientation.y,
             msg.pose.orientation.z, msg.pose.orientation.w) = self.latched_q
        self.servo_pub.publish(msg)
        self.guarded_pub.publish(msg)

    def _set_guard_state(self, state: str) -> None:
        self.guard_state = state
        if state != self.last_guard_state:
            self.last_guard_state = state
            self.guard_pub.publish(String(data=state))

    # ------------------------------------------------------------------- camera model
    def _camera_tf(self):
        try:
            tf = self.tf_buffer.lookup_transform(self.task.planning_frame, CAMERA_FRAME, Time())
        except Exception:  # noqa: BLE001
            return None
        q, tr = tf.transform.rotation, tf.transform.translation
        x, y, z, w = q.x, q.y, q.z, q.w
        rot = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        return rot, np.array([tr.x, tr.y, tr.z])

    def _intrinsics(self):
        info = self.camera_info()
        if not info or not info.get("k"):
            return None
        k = info["k"]
        return k[0], k[4], k[2], k[5]

    def screen_axes(self):
        """Planning-frame xy directions of image right and image up."""
        cam = self._camera_tf()
        if cam is None:
            return (-1.0, 0.0), (0.0, -1.0)  # 9a sim camera
        rot = cam[0]
        right, up = rot[:2, 0], -rot[:2, 1]
        right = right / (np.linalg.norm(right) or 1.0)
        up = up / (np.linalg.norm(up) or 1.0)
        return (float(right[0]), float(right[1])), (float(up[0]), float(up[1]))

    def project(self, pts_xyz):
        cam, k = self._camera_tf(), self._intrinsics()
        if cam is None or k is None:
            return None
        rot, t = cam
        fx, fy, cx, cy = k
        out = []
        for p in pts_xyz:
            pc = rot.T @ (np.asarray(p, float) - t)
            out.append(None if pc[2] <= 1e-6 else [float(fx * pc[0] / pc[2] + cx), float(fy * pc[1] / pc[2] + cy)])
        return out

    def unproject(self, u: float, v: float, plane_z: float):
        cam, k = self._camera_tf(), self._intrinsics()
        if cam is None or k is None:
            return None
        rot, t = cam
        fx, fy, cx, cy = k
        d = rot @ np.array([(u - cx) / fx, (v - cy) / fy, 1.0])
        if abs(d[2]) < 1e-9:
            return None
        s = (plane_z - t[2]) / d[2]
        if s <= 0:
            return None
        p = t + s * d
        return float(p[0]), float(p[1])

    def tip_z(self) -> float:
        return self.task.table_z + self.task.tip_clearance_nominal

    def area_corners(self, margin: float = 0.0, z: Optional[float] = None):
        (cx, cy), (sx, sy) = self.task.area_center, self.task.area_size
        hx, hy = sx / 2 + margin, sy / 2 + margin
        z = self.task.table_z if z is None else z
        return [(cx - hx, cy - hy, z), (cx + hx, cy - hy, z), (cx + hx, cy + hy, z), (cx - hx, cy + hy, z)]

    # ------------------------------------------------------------------- camera setup
    def latest_frame(self):
        f = self.frames.latest()
        if f is None or time.monotonic() - f[1] > self.image_stale:
            return None
        return f

    def auto_roi(self, image_size) -> tuple[int, int, int, int]:
        """Square ROI around the push area (plus ``roi_margin``) from the camera model."""
        uv = self.project(self.area_corners(self.roi_margin))
        w, h = image_size
        if not uv or any(p is None for p in uv):
            side = min(w, h)
            return ((w - side) // 2, (h - side) // 2, side, side)
        us, vs = [p[0] for p in uv], [p[1] for p in uv]
        side = int(math.ceil(max(max(us) - min(us), max(vs) - min(vs))))
        cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
        return ic.CameraSetup.clamp_roi((cu - side / 2, cv - side / 2, side, side), image_size)

    def _ensure_camera_setup(self, frame: np.ndarray) -> Optional[ic.CameraSetup]:
        if self.cam is not None:
            return self.cam
        size = (frame.shape[1], frame.shape[0])
        if self._camera_tf() is None:
            return None  # wait for TF so the auto ROI is right
        self._save_camera_setup(ic.CameraSetup(size, self.auto_roi(size), self.default_threshold,
                                               {"roi": "auto"}))
        return self.cam

    def _save_camera_setup(self, cam: ic.CameraSetup) -> None:
        cam.meta["feedback"] = self.feedback
        cam.save(self.cam_dir)
        self.cam = cam
        n = self.rec_cfg["image_size"]
        d = DATA / "calibration" / f"{self.mode}_feedback"
        ic.CameraSetup((n, n), (0, 0, n, n), cam.threshold,
                       {"note": "crop for /pusht/feedback_image (already the ROI at policy size)",
                        "roi_in_camera": list(cam.crop), "feedback": self.feedback}).save(d)
        _chown_like(DATA / "calibration", DATA)

    def set_roi(self, roi=None) -> dict:
        if self.recording:
            raise ValueError("not while recording")
        f = self.latest_frame()
        if f is None:
            raise ValueError("no fresh camera frame")
        size = (f[3].shape[1], f[3].shape[0])
        thr = self.cam.threshold if self.cam else self.default_threshold
        crop = self.auto_roi(size) if roi is None else ic.CameraSetup.clamp_roi(roi, size)
        self._save_camera_setup(ic.CameraSetup(size, crop, thr, {"roi": "auto" if roi is None else "manual"}))
        return self.camera_info_dict()

    def set_threshold(self, thr: dict) -> dict:
        if self.recording:
            raise ValueError("not while recording")
        if self.cam is None:
            raise ValueError("no ROI yet (no camera frame)")
        self._save_camera_setup(ic.CameraSetup(self.cam.image_size, self.cam.crop, ic.HsvRange.from_dict(thr),
                                               dict(self.cam.meta)))
        return self.camera_info_dict()

    def pick_color(self, u: float, v: float) -> dict:
        """Set the T colour range from a 9 x 9 patch around a full-frame pixel on the T."""
        f = self.latest_frame()
        if f is None or self.cam is None:
            raise ValueError("no fresh camera frame")
        img = f[3]
        x, y = int(u), int(v)
        patch = img[max(0, y - 4):y + 5, max(0, x - 4):x + 5]
        if patch.size == 0:
            raise ValueError("pixel outside the image")
        hsv = cv2.cvtColor(np.ascontiguousarray(patch), cv2.COLOR_RGB2HSV).reshape(-1, 3)
        h, s, val = (int(x) for x in np.median(hsv, axis=0))
        if s < 40:
            raise ValueError("that pixel has no colour (grey / white / black); click on the T")
        lo, hi = h - 12, h + 12
        thr = {"hue": [lo % 180, hi % 180], "sat_min": max(40, s - 70), "val": [max(10, val - 90), 255]}
        return self.set_threshold(thr)

    def camera_info_dict(self) -> Optional[dict]:
        if self.cam is None:
            return None
        return {"dir": str(self.cam_dir), "roi": list(self.cam.crop), "image_size": list(self.cam.image_size),
                "threshold": self.cam.threshold.to_dict(), "meta": self.cam.meta}

    def feedback_png(self, mode: Optional[str] = None) -> Optional[bytes]:
        """The policy / dataset image of the newest frame (what the recorder stores)."""
        f = self.latest_frame()
        if f is None:
            return None
        cam = self._ensure_camera_setup(f[3])
        if cam is None:
            return None
        img = ic.feedback_image(cam.apply_crop(f[3]), mode or self.feedback, cam.threshold,
                                self.rec_cfg["image_size"])
        return cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()

    def set_feedback(self, mode: str) -> None:
        if mode not in ic.FEEDBACK_MODES:
            raise ValueError(f"feedback must be one of {ic.FEEDBACK_MODES}")
        if self.recording:
            raise ValueError("not while recording")
        self.feedback = mode
        if self.cam is not None:
            self._save_camera_setup(self.cam)

    # ------------------------------------------------------------------------- recorder
    def _tick_10hz(self) -> None:
        f = self.latest_frame()
        cam = None if f is None else self._ensure_camera_setup(f[3])
        if cam is not None and self.feedback_pub.get_subscription_count() > 0:
            self._publish_feedback(cam, f[3])
        if not self.recording or self.buffer is None:
            return
        now = self.now()
        sample = ic.Sample(
            t=now, image=None if f is None else f[3],
            image_t=now - (time.monotonic() - f[1]) if f is not None else -math.inf,
            eef_xy=None if self.eef is None else self.eef[:2], action_xy=self.core.target,
            joints=self.joints)
        try:
            self.buffer.add(sample)
            self.rec_error = ""
        except ValueError as exc:
            self.rec_error = str(exc)
            return
        self._set_rec_state(f"recording:{len(self.buffer)}")

    def _publish_feedback(self, cam: ic.CameraSetup, frame: np.ndarray) -> None:
        try:
            img = ic.feedback_image(cam.apply_crop(frame), self.feedback, cam.threshold, self.rec_cfg["image_size"])
        except ValueError:
            return
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = CAMERA_FRAME
        msg.height, msg.width = img.shape[:2]
        msg.encoding, msg.step = "rgb8", img.shape[1] * 3
        msg.data = img.tobytes()
        self.feedback_pub.publish(msg)

    def _set_rec_state(self, state: str) -> None:
        if state != self.rec_state:
            self.rec_state = state
            self.rec_pub.publish(String(data=state))

    def _heartbeat(self) -> None:
        self.rec_pub.publish(String(data=self.rec_state))
        self.man_pub.publish(String(data=self.man_state))

    # ------------------------------------------------------------------- episode runner
    def _set_man(self, state: str, note: str = "") -> None:
        if (state, note) == (self.man_state, self.man_note):
            return
        self.man_state, self.man_note = state, note
        self.man_pub.publish(String(data=state))
        if not state.startswith("record:"):
            self.get_logger().info(f"episodes: {state} {note}")

    def start_session(self, dataset: str, operator: str, n_episodes: int, input_device: str,
                      episode_seconds: float, start_from_home: bool, wait_before_record: bool) -> None:
        if self.man_thread and self.man_thread.is_alive():
            raise ValueError(f"a run is active ({self.man_state})")
        if self.cam is None:
            raise ValueError("no camera ROI yet (no camera frame or TF)")
        if input_device not in ("teleop", "policy"):
            raise ValueError("input_device must be teleop or policy")
        if not 5.0 <= episode_seconds <= 600.0:
            raise ValueError("episode_seconds must be in [5, 600]")
        name = "".join(ch for ch in dataset if ch.isalnum() or ch in "_-.") or "pusht_cr3a_sim"
        self.session = {"dataset": name, "operator": operator, "n_episodes": max(1, int(n_episodes)),
                        "input_device": input_device, "episode_seconds": float(episode_seconds),
                        "start_from_home": bool(start_from_home),
                        "wait_before_record": bool(wait_before_record), "done": 0, "saved": 0}
        self.man_cmd = None
        if not self.enabled:
            self.set_enabled(True)
        self.man_thread = threading.Thread(target=self._run_session, daemon=True)
        self.man_thread.start()

    def command(self, cmd: str) -> None:
        if cmd not in ("record", "stop", "discard", "abort"):
            raise ValueError("unknown command")
        if not (self.man_thread and self.man_thread.is_alive()):
            raise ValueError("no run active")
        self.man_cmd = cmd

    def _check_abort(self) -> None:
        if self.man_cmd == "abort":
            raise ManagerAbort("operator abort")
        if not self.enabled:
            raise ManagerAbort("guard disabled")

    def _wait(self, cond, timeout: float, what: str) -> None:
        t0 = time.monotonic()
        while not cond():
            self._check_abort()
            if time.monotonic() - t0 > timeout:
                raise TimeoutError(what)
            time.sleep(0.02)

    def _hold_here(self) -> None:
        with self.lock:
            self.owner = "manager"
            self.core.set_source(ic.SOURCE_POSE)
            self.path = []
            self.pose_cmd = self.core.target or (self.eef[:2] if self.eef else None)

    def _lift(self, up: bool) -> None:
        self.set_lift(up)
        self._wait(lambda: self.lift_state() == ("up" if up else "down") and self.latched_z is not None,
                   self.ep_cfg["lift_timeout"], "lift")

    def _go_home(self) -> tuple[float, float]:
        home = tuple(self.task.home_candidates[0])
        with self.lock:
            self.owner = "manager"
            self.core.set_source(ic.SOURCE_POSE)
            self.path, self.pose_cmd = [], home
        tol = self.ep_cfg["home_tolerance"]
        self._wait(lambda: self.eef is not None and math.hypot(self.eef[0] - home[0], self.eef[1] - home[1]) < tol,
                   self.ep_cfg["home_timeout"], "home")
        return home

    def _run_session(self) -> None:
        sess = self.session
        try:
            while sess["done"] < sess["n_episodes"]:
                self._run_episode(sess)
                sess["done"] += 1
            self._set_man("idle", f"{sess['saved']} of {sess['done']} episode(s) saved")
        except ManagerAbort as exc:
            self._safe_stop()
            self._set_man("idle", str(exc))
        except Exception as exc:  # noqa: BLE001
            self._safe_stop()
            self._set_man(f"fault:{type(exc).__name__}", str(exc))
        finally:
            with self.lock:
                self.owner = "ui"
                self.pose_cmd = None
            self.episode_t0 = None

    def _safe_stop(self) -> None:
        self.recording = False
        self.buffer = None
        self._set_rec_state("idle")
        if self.enabled:
            self._hold_here()

    def _run_episode(self, sess: dict) -> None:
        self.man_cmd = None
        k = sess["done"] + 1
        home = None
        if sess["start_from_home"]:
            self._hold_here()
            self._set_man("reset:lift", f"episode {k}")
            self._lift(True)
            self._set_man("reset:home", f"episode {k}")
            home = self._go_home()
            self._set_man("reset:lower", f"episode {k}")
            self._lift(False)
            time.sleep(self.ep_cfg["lower_settle"])
        if sess["wait_before_record"]:
            with self.lock:
                self.owner = "ui"   # the operator may position the tool before recording
            self._set_man("reset:ready", f"episode {k}: arrange the T, then press Record")
            self._wait(lambda: self.man_cmd == "record", 3600, "ready")
            self.man_cmd = None

        policy = sess["input_device"] == "policy"
        duration = sess["episode_seconds"]
        max_frames = int(round(duration * self.rec_cfg["fps"]))
        self.buffer = ic.EpisodeBuffer(self.cam, sheet_origin=self.task.area_center, feedback=self.feedback,
                                       **self.rec_cfg)
        with self.lock:
            self.path, self.pose_cmd = [], None
            self.stick, self.stick_rx = (0.0, 0.0), -math.inf
            self.owner = "policy" if policy else "ui"
            self.core.set_source(ic.SOURCE_POSE if policy else ic.SOURCE_STICK)
        wall0 = time.monotonic()
        self.episode_t0 = self.now()
        self.recording = True
        reason = "duration"
        while True:
            self._check_abort()
            n = len(self.buffer)
            self._set_man(f"record:{n}", f"episode {k}")
            if self.man_cmd == "discard":
                reason = "discard"
                break
            if self.man_cmd == "stop":
                if policy:
                    self.man_cmd = None   # a policy episode always runs the full duration
                else:
                    reason = "operator_stop"
                    break
            if n >= max_frames:
                break
            time.sleep(0.05)
        self.recording = False
        self.episode_t0 = None
        buf, self.buffer = self.buffer, None
        self._set_rec_state("idle")
        self._hold_here()

        keep = reason != "discard" and len(buf) > 0
        meta = {
            "seed": -1, "home_xy": None if home is None else [round(v, 4) for v in home],
            "operator": sess["operator"], "mode": self.mode, "input_device": sess["input_device"],
            "stop_reason": reason, "episode_seconds": duration,
            "wall_seconds": round(time.monotonic() - wall0, 2), "success": None,
        }
        self.last_episode = {"kept": keep, "frames": len(buf), **meta, "timing": buf.timing.to_dict(buf.fps)}
        if keep:
            self._set_man("end:save", f"episode {k}")
            self.saving = True
            try:
                store = ic.RawStore(DATA / sess["dataset"])
                line = store.save(buf, meta, self.cam_dir)
                _chown_like(store.root, DATA)
                self.last_episode["raw_index"] = line["raw_index"]
                sess["saved"] += 1
            finally:
                self.saving = False
        self._set_man("end:done", f"episode {k} {'saved' if keep else 'discarded'}, {len(buf)} frames "
                      f"({len(buf) / buf.fps:.1f} s)")
        with self.lock:
            self.owner = "ui"
            self.pose_cmd = None

    # ---------------------------------------------------------------------- status
    def status(self) -> dict:
        z = self.tip_z()
        pts = self.area_corners(z=z) + [(h[0], h[1], z) for h in self.task.home_candidates]
        tgt, eef = self.core.target, self.eef
        if tgt is not None:
            pts.append((tgt[0], tgt[1], z))
        if eef is not None:
            pts.append((eef[0], eef[1], z))
        proj = self.project(pts)
        uv = None
        if proj is not None:
            nh = len(self.task.home_candidates)
            uv = {"area": proj[:4], "homes": proj[4:4 + nh]}
            k = 4 + nh
            if tgt is not None:
                uv["target"] = proj[k]
                k += 1
            if eef is not None:
                uv["eef"] = proj[k]
        f = self.frames.latest()
        rec_frames = 0 if self.buffer is None else len(self.buffer)
        sess = self.session
        return {
            "mode": self.mode,
            "guard": {"enabled": self.enabled, "state": self.guard_state, "source": self.core.source,
                      "owner": self.owner, "pose_mode_ok": self.pose_mode_ok,
                      "servo_halted": self.servo_halted, "servo_msg": self.servo_msg,
                      "moveit_executing": self.exec_active, "lift": self.lift_state(),
                      "latched_z": self.latched_z, "push_z": self.task.push_z,
                      "max_speed": self.core.config.max_speed, "target": tgt,
                      "eef": None if eef is None else list(eef),
                      "eef_age": None if eef is None else round(time.monotonic() - self.eef_rx, 3)},
            "camera": {"age": None if f is None else round(time.monotonic() - f[1], 3),
                       "seq": None if f is None else f[0], "uv": uv, "setup": self.camera_info_dict()},
            "feedback": self.feedback,
            "recorder": {"state": self.rec_state, "frames": rec_frames,
                         "seconds": round(rec_frames / self.rec_cfg["fps"], 1),
                         "error": self.rec_error, "saving": self.saving},
            "episodes": {"state": self.man_state, "note": self.man_note, "session": sess,
                         "last": self.last_episode, "defaults": self.ep_cfg},
            "area": {"center": list(self.task.area_center), "size": list(self.task.area_size)},
        }
