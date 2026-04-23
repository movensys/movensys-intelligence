"""ROS 2 node scaffold (PRD §11.5).

At M0 this is a minimal node that spins on a background thread.
- M4 adds camera subscribers (/image_top/*, /image_hand/*)
- M4 also adds the Isaac card-spawn publisher

Design notes:
- rclpy is imported lazily so `uvicorn main:app` starts even when ROS 2
  is not installed (dev machines, CI without ros-tooling, etc).
- `Ros2Bridge.start()` never raises; on import or init failure we stay
  in disabled mode and log a single warning.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from typing import Any

log = logging.getLogger("monopoly.ros2")


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


class Ros2Bridge:
    def __init__(self) -> None:
        self._rclpy: Any = None
        self._node: Any = None
        self._executor: Any = None
        self._thread: threading.Thread | None = None
        self._enabled: bool = False

    @property
    def enabled(self) -> bool:
        return self._enabled

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

        self._thread = threading.Thread(
            target=self._executor.spin, name="monopoly-ros2-spin", daemon=True
        )
        self._thread.start()
        self._enabled = True
        log.info(
            "ros2_bridge_started",
            extra={"isaac_topic": self.isaac_card_spawn_topic},
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
        log.info("ros2_bridge_stopped")
