"""ROS 2 node (PRD §11.5).

- Subscribes to 6 camera topics (/image_{top,hand}/{rgb,depth,camera_info})
  and caches the latest frame as a base64 JPEG dict for WS proxies.
- Publishes to ${MONOPOLY_ISAAC_TOPIC_CARD_SPAWN} (std_msgs/String JSON)
  whenever a Chance/Community Chest card is drawn (PRD §7.3.6).

Design notes:
- rclpy / cv2 / numpy / sensor_msgs are imported lazily inside start() so
  `uvicorn main:app` starts cleanly on dev machines without a ROS 2
  install. On any failure the bridge stays disabled and logs a single
  warning — behaviour verified by /api/ros2/health.
- Camera encoding mirrors movensys_vlm (§B.2 of the M4 audit) for wire
  compatibility with the shared cameras.html UI.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import threading
from typing import Any, Callable

log = logging.getLogger("monopoly.ros2")


# ---- frame cache keys ------------------------------------------------------

_STREAM_ATTRS: dict[str, str] = {
    "top_rgb":          "latest_top_rgb_image",
    "top_depth":        "latest_top_depth_image",
    "top_camera_info":  "latest_top_camera_info",
    "hand_rgb":         "latest_hand_rgb_image",
    "hand_depth":       "latest_hand_depth_image",
    "hand_camera_info": "latest_hand_camera_info",
}


def _rmw_loadable(rmw: str) -> bool:
    """rcl aborts the process with exit(1) when RMW_IMPLEMENTATION is set
    but the corresponding shared library is missing — try/except can't
    catch that. Load the .so first so we can refuse to call rclpy.init()
    cleanly instead."""
    try:
        ctypes.CDLL(f"lib{rmw}.so")
        return True
    except OSError as exc:
        log.warning("RMW shared lib unavailable: lib%s.so (%s)", rmw, exc)
        return False


# ---- image encoders (lazy cv2/numpy) --------------------------------------


def _make_encoders() -> tuple[Callable[..., Any] | None, Callable[..., Any] | None]:
    """Build (encode_rgb, encode_depth). Returns (None, None) when cv2 or
    numpy are unavailable — callers disable camera subscriptions in that
    case but keep the Isaac publisher working."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        log.warning("camera encoders unavailable (cv2/numpy missing): %s", exc)
        return None, None

    def encode_rgb(msg: Any) -> dict[str, Any] | None:
        try:
            img = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(
                msg.height, msg.width, 3
            )
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                return None
            return {
                "data": base64.b64encode(buf.tobytes()).decode("utf-8"),
                "encoding": "jpeg",
                "width": int(msg.width),
                "height": int(msg.height),
            }
        except Exception:
            return None

    def encode_depth(msg: Any) -> dict[str, Any] | None:
        try:
            depth = np.frombuffer(bytes(msg.data), dtype=np.float32).reshape(
                msg.height, msg.width
            )
            valid = (depth > 0.1) & (depth < 5.0)
            depth_norm = np.zeros_like(depth, dtype=np.uint8)
            depth_norm[valid] = ((depth[valid] - 0.1) / 4.9 * 255).astype(np.uint8)
            colored = cv2.applyColorMap(depth_norm, cv2.COLORMAP_TURBO)
            colored[~valid] = (0, 0, 0)
            ok, buf = cv2.imencode(".jpg", colored, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return None
            return {
                "data": base64.b64encode(buf.tobytes()).decode("utf-8"),
                "encoding": "jpeg_turbo_0.1-5m",
                "width": int(msg.width),
                "height": int(msg.height),
            }
        except Exception:
            return None

    return encode_rgb, encode_depth


def _camera_info_dict(msg: Any) -> dict[str, Any]:
    return {
        "width": int(msg.width),
        "height": int(msg.height),
        "distortion_model": msg.distortion_model,
        "k": list(msg.k),
        "d": list(msg.d),
        "r": list(msg.r),
        "p": list(msg.p),
        "binning_x": int(msg.binning_x),
        "binning_y": int(msg.binning_y),
    }


# ---- bridge ---------------------------------------------------------------


class Ros2Bridge:
    """FastAPI-side wrapper around the rclpy node lifecycle.

    Public surface consumed by router.py / game/manager.py:
      - enabled                        — bridge is spinning
      - isaac_card_spawn_topic         — current env-configured topic
      - latest_frame(stream)           — cached dict or None
      - publish_card_spawn(payload)    — fire-and-forget, True on success
    """

    def __init__(self) -> None:
        self._rclpy: Any = None
        self._node: Any = None
        self._executor: Any = None
        self._thread: threading.Thread | None = None
        self._enabled: bool = False
        self._cameras_enabled: bool = False
        # Latest encoded frames keyed by stream id; populated by callbacks.
        self._frames: dict[str, Any] = {k: None for k in _STREAM_ATTRS}
        self._card_pub: Any = None

    # ---- lifecycle -----------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def cameras_enabled(self) -> bool:
        return self._cameras_enabled

    @property
    def isaac_card_spawn_topic(self) -> str:
        return os.environ.get("MONOPOLY_ISAAC_TOPIC_CARD_SPAWN", "/isaac/card_spawn")

    def start(self) -> None:
        rmw = os.environ.get("RMW_IMPLEMENTATION", "").strip()
        if rmw and not _rmw_loadable(rmw):
            log.warning(
                "ROS 2 bridge disabled: RMW_IMPLEMENTATION=%r not installed", rmw
            )
            return

        try:
            import rclpy
            from rclpy.callback_groups import ReentrantCallbackGroup
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.node import Node
        except Exception as exc:
            log.warning("ROS 2 unavailable, bridge disabled: %s", exc)
            return

        try:
            rclpy.init(args=None)
        except Exception as exc:
            log.warning("rclpy.init failed, bridge disabled: %s", exc)
            return

        self._rclpy = rclpy
        self._node = Node("movensys_monopoly")
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)

        self._setup_camera_subscriptions(ReentrantCallbackGroup)
        self._setup_card_spawn_publisher()

        self._thread = threading.Thread(
            target=self._executor.spin, name="monopoly-ros2-spin", daemon=True
        )
        self._thread.start()
        self._enabled = True
        log.info(
            "ros2_bridge_started",
            extra={
                "isaac_topic": self.isaac_card_spawn_topic,
                "cameras_enabled": self._cameras_enabled,
            },
        )

    def stop(self) -> None:
        if not self._enabled:
            return
        try:
            if self._executor is not None:
                self._executor.shutdown()
            if self._node is not None:
                self._node.destroy_node()
            if self._rclpy is not None:
                self._rclpy.shutdown()
        except Exception as exc:
            log.warning("ros2_bridge_stop_error", extra={"error": str(exc)})
        self._enabled = False
        self._cameras_enabled = False
        log.info("ros2_bridge_stopped")

    # ---- camera subs ---------------------------------------------------

    def _setup_camera_subscriptions(self, cb_group_cls: Any) -> None:
        try:
            from sensor_msgs.msg import CameraInfo, Image  # type: ignore
        except Exception as exc:
            log.warning("camera subs disabled (sensor_msgs missing): %s", exc)
            return

        encode_rgb, encode_depth = _make_encoders()
        if encode_rgb is None or encode_depth is None:
            return

        cb = cb_group_cls()
        create = self._node.create_subscription

        def _set(key: str, value: Any) -> None:
            self._frames[key] = value

        create(Image, "/image_top/rgb",
               lambda m: _set("top_rgb", encode_rgb(m)), 1, callback_group=cb)
        create(Image, "/image_top/depth",
               lambda m: _set("top_depth", encode_depth(m)), 1, callback_group=cb)
        create(CameraInfo, "/image_top/camera_info",
               lambda m: _set("top_camera_info", _camera_info_dict(m)), 10, callback_group=cb)
        create(Image, "/image_hand/rgb",
               lambda m: _set("hand_rgb", encode_rgb(m)), 1, callback_group=cb)
        create(Image, "/image_hand/depth",
               lambda m: _set("hand_depth", encode_depth(m)), 1, callback_group=cb)
        create(CameraInfo, "/image_hand/camera_info",
               lambda m: _set("hand_camera_info", _camera_info_dict(m)), 10, callback_group=cb)

        self._cameras_enabled = True

    def latest_frame(self, stream: str) -> Any:
        """Return the cached encoded frame or None. `stream` must be one of
        _STREAM_ATTRS. Router caller is responsible for enumerating valid
        streams."""
        return self._frames.get(stream)

    # ---- isaac card-spawn publisher ------------------------------------

    def _setup_card_spawn_publisher(self) -> None:
        try:
            from std_msgs.msg import String  # type: ignore
        except Exception as exc:
            log.warning("isaac publisher disabled (std_msgs missing): %s", exc)
            return
        try:
            self._card_pub = self._node.create_publisher(
                String, self.isaac_card_spawn_topic, 10
            )
        except Exception as exc:
            log.warning("isaac publisher create failed: %s", exc)
            self._card_pub = None

    def publish_card_spawn(self, payload: dict[str, Any]) -> bool:
        """Publish a card-spawn event to Isaac. No-op when the bridge or
        publisher is disabled. Returns True on success. The topic accepts
        drops when no Isaac subscriber is attached — that's handled by
        rclpy/DDS, not by this method."""
        if not self._enabled or self._card_pub is None:
            return False
        try:
            from std_msgs.msg import String  # type: ignore
        except Exception:
            return False
        msg = String()
        msg.data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        try:
            self._card_pub.publish(msg)
            return True
        except Exception as exc:
            log.warning("isaac publish failed: %s", exc)
            return False
