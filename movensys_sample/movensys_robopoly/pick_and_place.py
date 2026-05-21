import logging
import math
import os
import random
import sys
import time
import requests
from typing import Optional

logger = logging.getLogger(__name__)
board_positions = {
    "GO": {
        "red_cube": {
            "pos": [-0.38973, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.37876, -0.15907, 0.3]
        },
        "green_cube": {
            "pos": [-0.32786, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.3323, -0.15907, 0.3]
        }
    },
    "BOSTON": {
        "red_cube": {
            "pos": [-0.38973, -0.07005, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.38615, -0.09402,0.3]
        },
        "green_cube": {
            "pos": [-0.32786, -0.07005, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.34041, -0.09396, 0.3]
        }
    },
    "SEOUL": {
        "red_cube": {
            "pos": [-0.38973, -0.00499, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.38615, -0.02562, 0.3]
        },
        "green_cube": {
            "pos": [-0.32786, -0.00499, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.34041, -0.02614, 0.3]
        }
    },
    "DESERT_ISLAND": {
        "red_cube": {
            "pos": [-0.38973, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.38615, 0.0405, 0.3]
        },
        "green_cube": {
            "pos": [-0.32786, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.34041, 0.04039, 0.3]
        }
    },
    "ELECTRIC_COMPANY": {
        "red_cube": {
            "pos": [-0.26, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.27231, 0.0405, 0.3]
        },
        "green_cube": {
            "pos": [-0.215, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.23001, 0.04039, 0.3]
        }
    },
    "TAIPEI": {
        "red_cube": {
            "pos": [-0.15, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.15219, 0.0405, 0.3]
        },
        "green_cube": {
            "pos": [-0.11, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.10781, 0.04039, 0.3]
        }
    },
    "SHANGHAI": {
        "red_cube": {
            "pos": [-0.035, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.03453, 0.0405, 0.3]
        },
        "green_cube": {
            "pos": [0.012, 0.05505, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.00802, 0.04039, 0.3]
        }
    },
    "NON-FREE_PARKING": {
        "red_cube": {
            "pos": [0.082, 0.055, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.07915, 0.0405, 0.3]
        },
        "green_cube": {
            "pos": [0.124, 0.055, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.12049, 0.04039, 0.3]
        }
    },
    "TOKYO": {
        "red_cube": {
            "pos": [0.082, -0.005, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.07915, -0.02496, 0.3]
        },
        "green_cube": {
            "pos": [0.124, -0.005, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.12049, -0.02767, 0.3]
        }
    },
    "BUSAN": {
        "red_cube": {
            "pos": [0.082, -0.07005, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.07915, -0.09243, 0.3]
        },
        "green_cube": {
            "pos": [0.124, -0.07005, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.12049, -0.09362, 0.3]
        }
    },
    "GO_TO_DESERT_ISLAND": {
        "red_cube": {
            "pos": [0.082, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.07991, -0.16428, 0.3]
        },
        "green_cube": {
            "pos": [0.124, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.12049, -0.16341, 0.3]
        }
    },
    "NEW_YORK": {
        "red_cube": {
            "pos": [-0.035, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.03824, -0.16428, 0.3]
        },
        "green_cube": {
            "pos": [0.012, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [0.00573, -0.16341, 0.3]
        }
    },
    "CHANCE": {
        "red_cube": {
            "pos": [-0.15, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.1527, -0.16428, 0.3]
        },
        "green_cube": {
            "pos": [-0.11, -0.14509, 0.3],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.11251, -0.16341, 0.3]
        }
    },
    "LONDON": {
        "red_cube": {
            "pos": [-0.26, -0.14509, 0.29],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.26724, -0.16428, 0.3]
        },
        "green_cube": {
            "pos": [-0.215, -0.14509, 0.29],
            "ori": [3.14, 0.0, -1.57],
            "sim_pos": [-0.22484, -0.16341, 0.3]
        }
    }
}

URL = "http://localhost:8000"

# When MOVENSYS_PNP_DRY_RUN is truthy, every HTTP call to the manipulator
# stack is skipped — motion/gripper requests log and return {} instead of
# hitting the arm. get_piece_info synthesizes a fixed pose so the rest of
# pick_and_place() runs end-to-end without hardware. Use for testing the
# monopoly server flow on a workstation with no robot attached.
DRY_RUN = os.environ.get("MOVENSYS_PNP_DRY_RUN", "").strip().lower() in (
    "1", "true", "yes", "y", "on",
)


def _post(path: str, payload: dict):
    if DRY_RUN:
        logger.info("[dry-run] POST %s %s", path, payload)
        return {}
    start = time.perf_counter()
    try:
        return requests.post(f"{URL}{path}", json=payload).json()
    finally:
        logger.info("[timing] POST %s: %.1f ms", path, (time.perf_counter() - start) * 1000.0)


def _get(path: str):
    if DRY_RUN:
        logger.info("[dry-run] GET %s", path)
        return {}
    start = time.perf_counter()
    try:
        return requests.get(f"{URL}{path}").json()
    finally:
        logger.info("[timing] GET %s: %.1f ms", path, (time.perf_counter() - start) * 1000.0)


def _sleep(seconds: float) -> None:
    # Real-hardware sleeps pace the arm between motion segments. In
    # dry-run the HTTP calls are stubbed instantly, so the sleeps become
    # pure wall-clock waste (~13s per dice roll) — skip them.
    if DRY_RUN:
        return
    time.sleep(seconds)


def _timed_method(label: str):
    def deco(fn):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                logger.info("[timing] %s: %.1f ms", label, (time.perf_counter() - start) * 1000.0)
        return wrapper
    return deco


# Motion API calls (/api/move/*) are blocking ROS service calls, so no
# pacing sleep is needed between motions. The gripper SetBool service
# returns before the jaws physically settle — keep a small post-gripper
# wait so subsequent motion doesn't drag/drop the cube.
_GRIPPER_SETTLE_S = 0.6


def move_base():
    absolute_joint_pose([0.0, 0.0, 0.5], [3.141, 0.0, -3.141])

# 6 motion movements
def absolute_cartesian_base(pos, ori):
    return _post("/api/move/absolute_cartesian_base", {"pos": pos, "ori": ori})

def relative_cartesian_base(pos, ori):
    return _post("/api/move/relative_cartesian_base", {"pos": pos, "ori": ori})

def relative_cartesian_tool(pos, ori):
    return _post("/api/move/relative_cartesian_tool", {"pos": pos, "ori": ori})

def absolute_joint_pose(pos, ori):
    return _post("/api/move/absolute_joint_pose", {"pos": pos, "ori": ori})

def joint_absolute(names, values):
    return _post("/api/move/joint_absolute", {"joint_names": names, "joint_values": values})

def joint_relative(names, values):
    return _post("/api/move/joint_relative", {"joint_names": names, "joint_values": values})

# 3 assistance functions
def gripper(close: bool):
    return _post("/api/services/gripper", {"data": close})

def get_eef_pose():
    return _get("/api/services/get_eef_pose")

def set_scales(vel, acc):
    return _post("/api/config/scales", {"vel_scale": vel, "acc_scale": acc})

class PnP:
    _BIN_CENTERS = (0.0, -math.pi / 2, -math.pi, math.pi / 2)

    def __init__(self, target_object: str = "red_cube", is_YOLO: bool = True, delay_exec: float = 2.0):
        self.delay_exec = delay_exec
        self.is_YOLO = is_YOLO

        # mapping target_object to number
        self.target_object = target_object
        target_object_mapper: dict = {"red_cube": 0, "green_cube": 1, "dice": 2}
        self.target_num = target_object_mapper.get(self.target_object)
        if self.target_num is None:
            raise ValueError(f"Unknown target_object '{self.target_object}'. Choose one of: {list(target_object_mapper)}")

        # mapping target object to support YOLO & Isaac via ROS2 topic
        if is_YOLO:
            self.TARGET_STR = ("yolo_cube_red", "yolo_cube_green", "dice")
        else:
            self.TARGET_STR = ("piece_2", "piece_1", "dice")
        
        # This offset is dependent for cube size.
        self.YOLO_dice_offset_x: float = 0.015  # [m]
        self.YOLO_dice_offset_y: float = -0.075  # [m]
        self.YOLO_piece_offset_x: float = 0.011  # [m]
        self.YOLO_piece_offset_y: float = -0.08 # [m]
        

        self.pos: Optional[dict] = None
        self.ori: Optional[dict] = None
        self.yaw: Optional[float] = None

        # Wall-clock time (time.time()) of the instant the gripper opened to
        # release the dice in _dest_move. main() uses this to ignore stale
        # /api/topics/dice_number cached from before/during the lift — only a
        # YOLO publication newer than (drop_time + settle) reflects the rolled
        # face.
        self._dice_drop_time: Optional[float] = None

    @staticmethod
    def _quaternion_to_yaw(qw: float, qx: float, qy: float, qz: float) -> float:
        siny_cosp = 2.0 * (qw * qz + qx * qy)
        cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
        return math.atan2(siny_cosp, cosy_cosp)

    @staticmethod
    def _init_move(target_object: str = "dice"):
        if target_object == "dice":
            absolute_cartesian_base([0.32040, -0.01058, 0.42], [3.141, 0.0, -3.141])
        else:
            # absolute_cartesian_base([-0.12857, 0.0, 0.3500], [3.141, 0.0, -3.141])
            absolute_cartesian_base([-0.18, 0.035, 0.52], [3.141, 0.0, -3.141])

    @_timed_method("toward_target")
    def _toward_target(self, target_object: str = "dice", target_pos: list = [0.0, 0.0, 0.0], target_ori: list = [0.0, 0.0, 0.0]):
        if target_object == "dice":
            if self.is_YOLO:
                relative_cartesian_tool(target_pos, target_ori)
            else:
                absolute_cartesian_base(target_pos, target_ori)

            # Go down
            relative_cartesian_tool([0.0,0.0,0.01], [0.0,0.0,0.0])
        else:
            # Go upside of the piece
            if self.is_YOLO:
                print(target_pos)
                relative_cartesian_tool(target_pos, target_ori)
            else:
                absolute_cartesian_base(target_pos, target_ori)

            # Go down
            relative_cartesian_tool([0.0,0.0,0.025], [0.0,0.0,0.0])

    @_timed_method("dest_move")
    def _dest_move(self, target_object: str = "dice", board_pos: str = "GO"):
        if target_object == "dice":
            # Go up
            relative_cartesian_tool([0.0,0.0,-0.1], [0.0,0.0,0.0])

            # place — release the dice and stamp the drop instant so main()
            # can wait for a post-roll YOLO detection.
            gripper(close=False)
            self._dice_drop_time = time.time()
            _sleep(_GRIPPER_SETTLE_S)

            # Retreat to the dice init pose. The gripper hovering ~10cm
            # above the dropped dice blocks the top camera, so YOLO can
            # never see the rolled face. The init pose was clear enough
            # for the pre-pickup detection — it's clear enough for the
            # post-roll one too.
            self._init_move("dice")
        else:
            # Go up
            relative_cartesian_tool([0.0,0.0,-0.050], [0.0,0.0,0.0])

            # Go upper side of target pos.
            if self.is_YOLO:
                target_pos = board_positions[board_pos][target_object]["pos"]
            else:
                target_pos = board_positions[board_pos][target_object]["sim_pos"]
            target_pos[2] = target_pos[2] + 0.035
            absolute_cartesian_base(target_pos, board_positions[board_pos][target_object]["ori"])

            # Go down
            relative_cartesian_tool([0.0,0.0,0.055], [0.0,0.0,0.0])

            # place
            gripper(close=False)
            _sleep(_GRIPPER_SETTLE_S)

            # Go up and prepare to go init pos
            relative_cartesian_tool([0.0,0.0,-0.06], [0.0,0.0,0.0])

    @_timed_method("get_piece_info")
    def get_piece_info(self, min_received_at: Optional[float] = None) -> bool:
        _target_object = self.TARGET_STR[self.target_num]

        if DRY_RUN:
            # Synthetic pose — pick_and_place math (yaw checks, target_pos
            # construction) needs non-None values. Numbers are arbitrary
            # but in the same shape the real topic would return.
            self.pos = {"x": 0.0, "y": 0.0, "z": 0.3}
            self.ori = {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
            self.yaw = 0.0
            logger.info("[dry-run] synthetic piece info for %s", _target_object)
            return True

        if self.is_YOLO:
            resp = requests.get(f"{URL}/api/topics/yolo_tf")

            # Error detection 1. YOLO result is published at /tf
            if resp.status_code == 503:
                logger.info("YOLO /tf unavailable: %s", resp.json().get("detail", ""))
                return False
            resp.raise_for_status()

            # Read
            tf_all = resp.json()

            # Error detection 2. If there is no YOLO detection, there is no result at /tf.
            if _target_object not in tf_all:
                logger.info("%s not detected (have: %s)", _target_object, list(tf_all))
                return False

            # find the result
            tf = tf_all[_target_object]
            # Reject cached TF entries older than the caller-supplied cutoff.
            # Used by the fallback search to ignore stale detections from
            # before the probe motion.
            if min_received_at is not None and tf.get("received_at", 0.0) < min_received_at:
                logger.info("%s detection is stale (received_at=%.3f < %.3f)",
                            _target_object, tf.get("received_at", 0.0), min_received_at)
                return False
            self.pos = {"x": round(tf["translation"]["x"], 5), "y": round(tf["translation"]["y"], 5), "z": round(tf["translation"]["z"], 5)}
            self.ori = {"w": tf["rotation"]["w"], "x": tf["rotation"]["x"], "y": tf["rotation"]["y"], "z": tf["rotation"]["z"]}

        # Isaac
        else:
            URL_topic = f"{URL}/api/topics/{_target_object}"
            resp = requests.get(URL_topic)
            info = resp.json()
            self.pos = {"x": round(info["position"]["x"], 5), "y": round(info["position"]["y"], 5), "z": round(info["position"]["z"], 5)}
            self.ori = {"w": info["orientation"]["w"], "x": info["orientation"]["x"], "y": info["orientation"]["y"], "z": info["orientation"]["z"]}

        self.yaw = round(self._quaternion_to_yaw(self.ori["w"], self.ori["x"], self.ori["y"], self.ori["z"]), 5)
        return True
    
    @staticmethod
    def _checking_yaw(yaw: float) -> int:
        if -math.pi / 4 <= yaw < math.pi / 4:
            return 0
        elif -3 * math.pi / 4 <= yaw < -math.pi / 4:
            return 1
        elif math.pi / 4 <= yaw < 3 * math.pi / 4:
            return 3
        else:
            return 2

    def converting_yaw(self, yaw_status: int, target_yaw_status: int) -> None:
        # Shift yaw by the bin-center delta (multiple of pi/2)
        delta = self._BIN_CENTERS[target_yaw_status] - self._BIN_CENTERS[yaw_status]
        # Then wrap to (-pi, pi].
        self.yaw = (self.yaw + delta + math.pi) % (2 * math.pi) - math.pi

    _SEARCH_OFFSETS = (
        ("front", ( 0.05,  0.0)),
        ("back",  (-0.05,  0.0)),
        ("right", ( 0.0,  -0.05)),
        ("left",  ( 0.0,   0.05)),
    )
    _SEARCH_SETTLE_S = 2.5

    @_timed_method("search_for_target")
    def _search_for_target(self) -> bool:
        """Fallback: nudge +/-5cm in base XY (front, back, right, left) and
        retry detection at each probe. Undoes each probe before the next so
        the arm ends at the original pose whether we succeed or fail."""
        for name, (dx, dy) in self._SEARCH_OFFSETS:
            logger.info("search: probing %s (dx=%+.2f, dy=%+.2f)", name, dx, dy)
            mv = relative_cartesian_base([dx, dy, 0.0], [0.0, 0.0, 0.0])
            if not mv.get("success", False):
                logger.warning("search: %s probe motion failed: %s", name, mv.get("message"))
                continue
            probe_time = time.time()
            time.sleep(self._SEARCH_SETTLE_S)
            found = self.get_piece_info(min_received_at=probe_time)
            if found:
                logger.info("search: detected %s after %s probe", self.target_object, name)
                return True

            relative_cartesian_base([-dx, -dy, 0.0], [0.0, 0.0, 0.0])
            probe_time = time.time()
            time.sleep(self._SEARCH_SETTLE_S)
            found = self.get_piece_info(min_received_at=probe_time)
            if found:
                logger.info("search: detected %s after %s probe", self.target_object, name)
                return True

        return False

    @_timed_method("pick_and_place")
    def pick_and_place(self, board_pos: str = "GO"):
        if board_pos not in board_positions:
            raise ValueError(f"Unknown board_pos '{board_pos}'. Choose one of: {list(board_positions)}")

        gripper(close=False)
        _sleep(_GRIPPER_SETTLE_S)
        # move to initial position
        
        # For YOLO, we need to set offset
        if self.is_YOLO:
            if self.target_object == "dice":
                self.pos['x'] += self.YOLO_dice_offset_x
                self.pos['y'] += self.YOLO_dice_offset_y
            else:
                self.pos['x'] += self.YOLO_piece_offset_x
                self.pos['y'] += self.YOLO_piece_offset_y

        # This is for dice.
        if self.target_object == "dice":
            yaw_status = self._checking_yaw(self.yaw)
            print(self.yaw)
            # For using target_yaw_status = 3, we should change `movensys_manipulator's joint6 limitation`
            self.converting_yaw(yaw_status=yaw_status, target_yaw_status=1)
        # This is for piece pnp.
        else:
            yaw_status = self._checking_yaw(self.yaw)
            # clockwisely rotate 90 degree. (Left-column tiles.)
            if board_pos in ("GO", "BOSTON", "SEOUL", "DESERT_ISLAND"):
                self.converting_yaw(yaw_status=yaw_status, target_yaw_status=1)

            # Counter clockwisely rotate -90 degree. (Right-column tiles.)
            elif board_pos in ("NON-FREE_PARKING", "TOKYO", "BUSAN", "GO_TO_DESERT_ISLAND"):
                self.converting_yaw(yaw_status=yaw_status, target_yaw_status=1)

            # Rotate 180 degree. Looking front side.
            else:
                self.converting_yaw(yaw_status=yaw_status, target_yaw_status=1)

        # move toward target
        if self.is_YOLO:
            if self.target_object == "dice":
                target_pos = [self.pos['x'], self.pos['y'], 0.12]
            else:
                target_pos = [self.pos['x'], self.pos['y'], 0.22]
            target_ori = [0.0, 0.0, self.yaw]
            logger.info(f"{self.target_object}: x={self.pos['x']}, y={self.pos['y']}, z={self.pos['z']}, yaw={self.yaw}")
        else:
            if self.target_object == "dice":
                target_pos = [self.pos['y'], -self.pos['x'], 0.3]
            else:
                target_pos = [self.pos['y'], -self.pos['x'], 0.3]
            target_ori = [-3.14, 0.0, self.yaw]
            logger.info(f"{self.target_object}: x={self.pos['y']}, y={-self.pos['x']}, z={self.pos['z']}, yaw={self.yaw}")
        
        self._toward_target(self.target_object, target_pos, target_ori)

        # grasp
        gripper(close=True)
        _sleep(_GRIPPER_SETTLE_S)

        # move to destination
        self._dest_move(self.target_object, board_pos)





# After the dice is released we wait this long for it to physically stop
# rolling before trusting a YOLO reading. The polling loop then keeps
# checking up to _DICE_POLL_TIMEOUT_S in case YOLO publishes a little late.
_DICE_SETTLE_S = 1.5
_DICE_POLL_TIMEOUT_S = 5.0
_DICE_POLL_INTERVAL_S = 0.1


def _wait_for_rolled_dice_number(drop_time: float) -> Optional[int]:
    """Poll /api/topics/dice_number until YOLO publishes a value whose
    received_at is past (drop_time + settle) — i.e., detected after the dice
    finished rolling. Returns None if no fresh value arrives before timeout.
    """
    if DRY_RUN:
        # No physical dice was rolled and the orchestrator's cached
        # dice_number would just return a stale value forever. Sample.
        value = random.randint(1, 6)
        logger.info("[dry-run] synthetic rolled dice_number=%s", value)
        return value
    time.sleep(_DICE_SETTLE_S)
    fresh_after = drop_time + _DICE_SETTLE_S
    deadline = time.time() + _DICE_POLL_TIMEOUT_S
    while time.time() < deadline:
        try:
            resp = requests.get(f"{URL}/api/topics/dice_number", timeout=2.0)
        except Exception as exc:
            logger.warning("dice_number poll error: %s", exc)
            time.sleep(_DICE_POLL_INTERVAL_S)
            continue
        if resp.ok:
            payload = resp.json()
            received_at = payload.get("received_at", 0.0)
            value = payload.get("value")
            if value is not None and received_at >= fresh_after:
                return int(value)
        else:
            logger.warning("dice_number fetch returned %s: %s", resp.status_code, resp.text)
        time.sleep(_DICE_POLL_INTERVAL_S)
    return None


def _parse_is_yolo(token: str) -> bool:
    value = token.strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"Unrecognized is_YOLO value '{token}'. Use true/false.")


_READ_POLL_TIMEOUT_S = 8.0
_READ_POLL_INTERVAL_S = 0.2


def _read_dice_only(is_yolo: bool, pnp: "PnP", main_start: float) -> None:
    """User-turn dice path: the human has already thrown the die. Move the
    arm to the dice scan pose (so the gripper is out of the camera's way)
    and read whatever YOLO currently sees. No pickup, no drop, no
    freshness check — the dice was rolled BEFORE this script started, so
    the cached YOLO publish (which may have a received_at older than the
    arm motion) is exactly the value we want.

    Guarantees that DICE_NUMBER=<n> is printed before this function
    returns. If YOLO never publishes anything, we fall back to a default
    of 1 with a loud error log — emitting *something* lets the calling
    chain (router → apply_robot → end_turn) proceed instead of
    dead-ending on a 502 with no user-visible message. The operator will
    see the warning and can re-roll if the face is wrong.
    """
    init_start = time.perf_counter()
    logger.info("read mode: moving arm to dice scan pose")
    pnp._init_move("dice")
    time.sleep(2.0)
    logger.info(
        "[timing] read_init+settle: %.1f ms",
        (time.perf_counter() - init_start) * 1000.0,
    )

    value: Optional[int] = None
    last_status: Optional[int] = None
    last_detail: Optional[str] = None

    if DRY_RUN:
        value = random.randint(1, 6)
        logger.info("[dry-run] synthetic read dice_number=%s", value)
        print(f"DICE_NUMBER={value}", flush=True)
        logger.info("read mode: emitted DICE_NUMBER=%s", value)
        logger.info("[timing] read_total: %.1f ms", (time.perf_counter() - main_start) * 1000.0)
        return

    if is_yolo:
        deadline = time.time() + _READ_POLL_TIMEOUT_S
        attempts = 0
        while time.time() < deadline:
            attempts += 1
            try:
                resp = requests.get(f"{URL}/api/topics/dice_number", timeout=2.0)
                last_status = resp.status_code
                if resp.ok:
                    payload = resp.json()
                    cached = payload.get("value")
                    received_at = payload.get("received_at")
                    if cached is not None:
                        value = int(cached)
                        logger.info(
                            "read mode: got dice_number=%s after %d attempt(s) (received_at=%s)",
                            value, attempts, received_at,
                        )
                        break
                    last_detail = "ok but no 'value' field"
                else:
                    # 503 "No dice number received yet" lands here.
                    try:
                        last_detail = resp.json().get("detail")
                    except Exception:
                        last_detail = resp.text[:200]
            except Exception as exc:
                last_detail = repr(exc)
                logger.warning("dice_number fetch error: %s", exc)
            time.sleep(_READ_POLL_INTERVAL_S)

        if value is None:
            logger.error(
                "read mode: YOLO never returned a usable dice_number after %d attempt(s) "
                "(last status=%s, last detail=%s). Falling back to DICE_NUMBER=1 so the "
                "turn doesn't dead-end. Re-roll if this face is wrong.",
                attempts, last_status, last_detail,
            )
            value = 1
    else:
        value = random.randint(1, 6)

    print(f"DICE_NUMBER={value}", flush=True)
    logger.info("read mode: emitted DICE_NUMBER=%s", value)
    logger.info("[timing] read_total: %.1f ms", (time.perf_counter() - main_start) * 1000.0)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) < 4:
        raise SystemExit(
            "Usage: python3 pick_and_place.py <target_object> <board_pos> <is_YOLO> [mode]"
        )

    # is_YOLO drives PnP.TARGET_STR (yolo_cube_* vs piece_*) and per-method
    # branches throughout the class, so it must be parsed before PnP() is
    # instantiated.
    is_yolo = _parse_is_yolo(sys.argv[3])

    # Optional 4th arg. "roll" (default) is the full pick+drop chain used
    # on the robot turn. "read" is the user-turn path — the human has
    # already thrown the dice, we only need to look at it. Only valid
    # when target_object == "dice".
    mode = (sys.argv[4] if len(sys.argv) >= 5 else "roll").strip().lower()
    if mode not in ("roll", "read"):
        raise SystemExit(f"Unrecognized mode '{mode}'. Use 'roll' or 'read'.")
    if mode == "read" and sys.argv[1] != "dice":
        raise SystemExit("mode='read' is only valid for target_object='dice'")

    pnp = PnP(target_object=sys.argv[1], is_YOLO=is_yolo, delay_exec=2.0)

    main_start = time.perf_counter()

    if mode == "read":
        _read_dice_only(is_yolo, pnp, main_start)
        return

    # init
    init_start = time.perf_counter()
    pnp._init_move(sys.argv[1])
    init_done_at = time.time()
    time.sleep(3.0)
    logger.info("[timing] init_move+settle: %.1f ms", (time.perf_counter() - init_start) * 1000.0)

    # pick and place
    detect_start = time.perf_counter()
    if not pnp.get_piece_info(min_received_at=init_done_at if is_yolo else None):
        if is_yolo:
            logger.info("Initial detection missed, starting 4-direction fallback search")
            if not pnp._search_for_target():
                # Exit non-zero so the spawning router sees PNP_FAILED and
                # surfaces it to the frontend, instead of silently advancing
                # the game state while the physical cube never moved.
                logger.error("Failed to detect %s after search, aborting.", sys.argv[1])
                sys.exit(1)
        else:
            logger.error("Failed to get piece info, aborting.")
            sys.exit(1)
    logger.info("[timing] detect_phase: %.1f ms", (time.perf_counter() - detect_start) * 1000.0)

    pnp.pick_and_place(board_pos=sys.argv[2])

    logger.info("[timing] main_total: %.1f ms", (time.perf_counter() - main_start) * 1000.0)

    # Emit the rolled face. For YOLO we must wait until *after* the dice has
    # been released and settled — /api/topics/dice_number is just a cached
    # latest detection, so reading it without a freshness check would report
    # the face from before pickup (or a transient mid-lift detection).
    if sys.argv[1] == "dice":
        if is_yolo:
            drop_time = pnp._dice_drop_time
            if drop_time is None:
                logger.warning(
                    "Dice drop_time not recorded; falling back to immediate read (value may be stale)."
                )
                drop_time = 0.0
            value = _wait_for_rolled_dice_number(drop_time)
            if value is None:
                # YOLO never published a post-roll detection. Rather than
                # leave the router blocked waiting for DICE_NUMBER (which
                # would stall the whole turn), emit the latest cached value
                # so the game can advance. We log a warning so the operator
                # knows the reading may not reflect the true rolled face.
                logger.warning(
                    "No fresh dice_number after drop — falling back to latest cached value"
                )
                try:
                    resp = requests.get(f"{URL}/api/topics/dice_number", timeout=2.0)
                    if resp.ok:
                        cached = resp.json().get("value")
                        if cached is not None:
                            value = int(cached)
                except Exception as exc:
                    logger.warning("dice_number fallback fetch failed: %s", exc)
            if value is not None:
                print(f"DICE_NUMBER={value}", flush=True)
                logger.info("Detected rolled dice number: %s", value)
            else:
                logger.error(
                    "Unable to obtain any dice_number (drop_time=%.3f) — DICE_NUMBER not emitted",
                    drop_time,
                )
        else:
            value = random.randint(1, 6)
            print(f"DICE_NUMBER={value}", flush=True)
            logger.info("Sampled dice number: %s", value)

if __name__ == "__main__":
    main()
