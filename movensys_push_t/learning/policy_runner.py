"""policy_runner: drive the push_t planar guard from a trained checkpoint (host venv, GPU).

Adapted from movensys-imitation's ``movensys_imitation_ros/policy_runner.py`` (origin/devel, MIT)
for movensys_push_t: the observation is push_t's own ``/pusht/policy_image`` (the grayscale ROI
at 256 x 256, exactly what the recorder stored), so no camera crop is applied here.

    in   /pusht/policy_image       sensor_msgs/Image          256 x 256 rgb8 (gray in 3 channels)
    in   /wmx/moveit2/eef_pose     geometry_msgs/PoseStamped  tip (Link6) x, y
    in   /episode_recorder/state   std_msgs/String            gate: acts while "recording:<n>"
    out  /pusht/target_raw         geometry_msgs/PoseStamped  target for the guard (slow, normal)
    out  /pusht/policy_target      geometry_msgs/PoseStamped  raw prediction (every mode)
    out  /policy_runner/state      std_msgs/String            idle | running:<n> | stale | fault:<why>

Every 10 Hz tick (node clock, sim time in sim) while push_t records an episode it feeds the
newest image and the tip position in the sheet frame (planning frame minus the push-area centre)
to the policy and publishes the next target. Modes: ``shadow`` publishes only
``/pusht/policy_target`` (an operator drives with keyboard_teleop); ``slow`` keeps each target
within ``slow_step`` of the tip; ``normal`` publishes the policy output. The guard's limits apply
in every mode.

    source env.bash
    pusht-policy-runner --ros-args -p pretrained:=outputs/diffusion_s1/checkpoints/last/pretrained_model \\
        -p run_mode:=slow -p policy_overrides:="--policy.noise_scheduler_type=DDIM --policy.num_inference_steps=10"
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

ROOT = Path(__file__).resolve().parent.parent          # movensys_push_t/
RUN_MODES = ("shadow", "slow", "normal")


def clamp_area(xy, area_size, margin: float = 0.0):
    hx, hy = area_size[0] / 2 - margin, area_size[1] / 2 - margin
    return (float(min(max(xy[0], -hx), hx)), float(min(max(xy[1], -hy), hy)))


def limit_step(state_xy, target_xy, max_step: float):
    dx, dy = target_xy[0] - state_xy[0], target_xy[1] - state_xy[1]
    d = math.hypot(dx, dy)
    if max_step <= 0 or d <= max_step:
        return (float(target_xy[0]), float(target_xy[1]))
    k = max_step / d
    return (float(state_xy[0] + dx * k), float(state_xy[1] + dy * k))


def decode_rgb(msg: Image) -> np.ndarray:
    rows = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(msg.height, msg.step)
    if msg.encoding not in ("rgb8", "bgr8"):
        raise ValueError(f"unsupported encoding {msg.encoding}")
    img = rows[:, :msg.width * 3].reshape(msg.height, msg.width, 3)
    return np.ascontiguousarray(img[..., ::-1] if msg.encoding == "bgr8" else img)


class PolicyRunnerNode(Node):
    def __init__(self) -> None:
        super().__init__("policy_runner")
        p = {k: self.declare_parameter(k, v).value for k, v in {
            "pretrained": "",
            "policy_overrides": "",      # space-separated, e.g. "--policy.fm_num_steps=4"
            "device": "",
            "run_mode": "slow",
            "slow_step": 0.010,          # m per tick in slow mode (0.1 m/s at 10 Hz)
            "area_margin": 0.0,
            "rate_hz": 10.0,
            "max_image_age": 0.3,        # s (wall clock)
            "max_eef_age": 0.5,
            "config": str(ROOT / "config" / "imitation.yaml"),
        }.items()}
        if p["run_mode"] not in RUN_MODES:
            raise ValueError(f"run_mode must be one of {RUN_MODES}")
        if not p["pretrained"]:
            raise ValueError("set -p pretrained:=<.../checkpoints/last/pretrained_model>")
        task = (yaml.safe_load(Path(p["config"]).read_text()) or {}).get("task", {})
        self.origin = tuple(task.get("area_center", (-0.03, -0.05)))
        self.area_size = tuple(task.get("area_size", (0.60, 0.30)))
        self.run_mode, self.slow_step, self.area_margin = p["run_mode"], p["slow_step"], p["area_margin"]
        self.max_image_age, self.max_eef_age = p["max_image_age"], p["max_eef_age"]

        pretrained = Path(p["pretrained"]).expanduser()
        if not pretrained.is_absolute():
            pretrained = ROOT / pretrained
        from learning.inference import PolicyRunner  # torch import after the parameters are checked

        self.get_logger().info(f"loading {pretrained} ...")
        self.runner = PolicyRunner(pretrained, tuple(p["policy_overrides"].split()), p["device"] or None)
        self.get_logger().info(f"policy {self.runner.cfg.type} on {self.runner.cfg.device}, mode {self.run_mode}")

        self.image = None
        self.image_rx = -math.inf
        self.eef = None
        self.eef_rx = -math.inf
        self.recorder_state = "idle"
        self.active = False
        self.n_ticks = 0
        self.state = ""
        self.create_subscription(Image, "/pusht/policy_image", self._on_image, qos_profile_sensor_data)
        self.create_subscription(PoseStamped, "/wmx/moveit2/eef_pose", self._on_eef, 10)
        self.create_subscription(String, "/episode_recorder/state", self._on_recorder, 10)
        self.target_pub = self.create_publisher(PoseStamped, "/pusht/target_raw", 10)
        self.policy_pub = self.create_publisher(PoseStamped, "/pusht/policy_target", 10)
        self.state_pub = self.create_publisher(String, "~/state", 10)
        self.create_timer(1.0 / p["rate_hz"], self._tick)
        self._set_state("idle")

    def _on_image(self, msg: Image) -> None:
        self.image, self.image_rx = msg, time.monotonic()

    def _on_eef(self, msg: PoseStamped) -> None:
        self.eef, self.eef_rx = (msg.pose.position.x, msg.pose.position.y), time.monotonic()

    def _on_recorder(self, msg: String) -> None:
        self.recorder_state = msg.data

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_pub.publish(String(data=state))

    def _publish(self, pub, xy_sheet) -> None:
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "world_manipulator"
        msg.pose.position.x = float(xy_sheet[0] + self.origin[0])
        msg.pose.position.y = float(xy_sheet[1] + self.origin[1])
        msg.pose.orientation.w = 1.0
        pub.publish(msg)

    def _tick(self) -> None:
        recording = self.recorder_state.startswith("recording")
        if not recording:
            if self.active:
                self.get_logger().info(f"episode done after {self.n_ticks} policy ticks")
                self.active = False
            self._set_state("idle")
            return
        if not self.active:
            self.active, self.n_ticks = True, 0
            self.runner.reset()
            self.get_logger().info("episode start: policy history reset")
        now = time.monotonic()
        if (self.image is None or now - self.image_rx > self.max_image_age
                or self.eef is None or now - self.eef_rx > self.max_eef_age):
            self._set_state("stale")
            return
        state = (self.eef[0] - self.origin[0], self.eef[1] - self.origin[1])
        try:
            action = self.runner.act(decode_rgb(self.image), state)
        except Exception as exc:  # noqa: BLE001  keep the node alive
            self._set_state(f"fault:{exc}")
            self.get_logger().error(f"policy call failed: {exc}", throttle_duration_sec=5.0)
            return
        if not np.all(np.isfinite(action)):
            self._set_state("fault:nan")
            return
        target = clamp_area(action, self.area_size, self.area_margin)
        self._publish(self.policy_pub, target)
        if self.run_mode == "slow":
            target = limit_step(state, target, self.slow_step)
        if self.run_mode in ("slow", "normal"):
            self._publish(self.target_pub, target)
        self.n_ticks += 1
        self._set_state(f"running:{self.n_ticks}")
        if self.n_ticks % 50 == 1:
            self.get_logger().info(
                f"tick {self.n_ticks}: tip ({state[0] * 1000:.0f}, {state[1] * 1000:.0f}) mm -> target "
                f"({target[0] * 1000:.0f}, {target[1] * 1000:.0f}) mm, {self.runner.last_latency_ms:.1f} ms")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PolicyRunnerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
