"""rclpy-based subscriber for YOLO debug image topics.

Robopoly's original design route image data through the movensys_vlm
orchestrator (see doc/API.md note about no `rclpy` in robopoly), but the
operator's deploy flow only rebuilds the robopoly container — forcing a
VLM rebuild for the debug-image overlay was awkward in practice. This
module ships the subscription with robopoly so a single
`docker compose build` in movensys_robopoly/docker brings the feature up.

The subscriber spins in a background thread (rclpy `MultiThreadedExecutor`
on a dedicated thread) so FastAPI's asyncio loop is untouched.

Topics:
- /yolo_dice_detector/debug_image  — dice detector overlay
- /yolo_cube_detector/debug_image  — cube detector overlay

Both publish `sensor_msgs/Image` with either `rgb8` or `bgr8` encoding.
We JPEG-encode the latest frame as it arrives and cache the base64
payload so the FastAPI WS handler can serve it without copying every
poll.
"""
from __future__ import annotations

import base64
import logging
import threading
from typing import Optional

log = logging.getLogger("monopoly.ros_image")


class RosImageSubscriber:
    """Optional ROS subscriber. Falls back to None on import failure so the
    server still boots in environments without rclpy installed (e.g. dev
    machines outside the docker container)."""

    def __init__(self) -> None:
        self.latest_dice_debug: Optional[dict] = None
        self.latest_cube_debug: Optional[dict] = None
        self._thread: Optional[threading.Thread] = None
        self._executor = None
        self._node = None
        self._available = False
        self._np = None
        self._cv2 = None

        try:
            import rclpy  # noqa: F401
            from sensor_msgs.msg import Image  # noqa: F401
            import numpy as np
            import cv2
        except ImportError as exc:
            log.warning(
                "rclpy / sensor_msgs / numpy / cv2 unavailable — YOLO debug "
                "image overlay disabled (%s). The dice and cube debug streams "
                "will be empty; the rest of the game is unaffected.",
                exc,
            )
            return

        self._np = np
        self._cv2 = cv2
        self._available = True

    def start(self) -> None:
        if not self._available or self._thread is not None:
            return
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.callback_groups import ReentrantCallbackGroup
        from rclpy.node import Node
        from sensor_msgs.msg import Image

        if not rclpy.ok():
            try:
                rclpy.init()
            except Exception as exc:
                log.warning("rclpy.init failed — disabling YOLO overlay: %s", exc)
                self._available = False
                return

        class _Node(Node):
            def __init__(self, owner: "RosImageSubscriber") -> None:
                super().__init__("movensys_monopoly_yolo_overlay")
                self._owner = owner
                cb = ReentrantCallbackGroup()
                self.create_subscription(
                    Image, "/yolo_dice_detector/debug_image",
                    self._on_dice, 1, callback_group=cb,
                )
                self.create_subscription(
                    Image, "/yolo_cube_detector/debug_image",
                    self._on_cube, 1, callback_group=cb,
                )

            def _on_dice(self, msg: Image) -> None:
                self._owner.latest_dice_debug = self._owner._encode(msg)

            def _on_cube(self, msg: Image) -> None:
                self._owner.latest_cube_debug = self._owner._encode(msg)

        self._node = _Node(self)
        self._executor = MultiThreadedExecutor()
        self._executor.add_node(self._node)

        def _spin() -> None:
            try:
                self._executor.spin()
            except Exception:
                log.exception("YOLO overlay executor crashed")

        self._thread = threading.Thread(
            target=_spin, name="yolo-overlay-spin", daemon=True,
        )
        self._thread.start()
        log.info("YOLO debug-image subscriber started")

    def stop(self) -> None:
        if self._executor is not None:
            try:
                self._executor.shutdown()
            except Exception:
                pass
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
        try:
            import rclpy
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass

    def _encode(self, msg) -> Optional[dict]:
        try:
            img = self._np.frombuffer(bytes(msg.data), dtype=self._np.uint8)
            img = img.reshape(msg.height, msg.width, 3)
            if msg.encoding == "rgb8":
                bgr = self._cv2.cvtColor(img, self._cv2.COLOR_RGB2BGR)
            else:
                bgr = img
            ok, buf = self._cv2.imencode(
                ".jpg", bgr, [self._cv2.IMWRITE_JPEG_QUALITY, 80],
            )
            if not ok:
                return None
            return {
                "data": base64.b64encode(buf.tobytes()).decode("utf-8"),
                "encoding": "jpeg",
                "width": msg.width,
                "height": msg.height,
            }
        except Exception as exc:
            log.debug("encode failure: %s", exc)
            return None
