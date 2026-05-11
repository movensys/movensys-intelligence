import logging
import math
import sys
import time
import requests
from typing import Optional

logger = logging.getLogger(__name__)
board_positions = {
    "GO": {
        "red_cube": {
            "pos": [-0.3781, -0.16726, 0.29],
            "ori": [3.14, 0.0, -1.57]
        },
        "green_cube": {
            "pos": [-0.32786, -0.16726, 0.29],
            "ori": [3.14, 0.0, -1.57]
        }
    },
    "SUWON": {
        "red_cube": {
            "pos": [-0.38338, -0.09155, 0.29],
            "ori": [3.14, 0.0, -1.57]
        },
        "green_cube": {
            "pos": [-0.32786, -0.09155, 0.29],
            "ori": [3.14, 0.0, -1.57]
        }
    },
    "SEOUL": {
        "red_cube": {
            "pos": [-0.38338, -0.02342, 0.29],
            "ori": [3.14, 0.0, -1.57]
        },
        "green_cube": {
            "pos": [-0.32786, -0.02396, 0.29],
            "ori": [3.14, 0.0, -1.57]
        }
    },
    "INCHEON_AIRPORT": {
        "red_cube": {
            "pos": [-0.38338, 0.03822, 0.29],
            "ori": [3.14, 0.0, -1.57]
        },
        "green_cube": {
            "pos": [-0.32786, 0.03857, 0.29],
            "ori": [3.14, 0.0, -1.57]
        }
    },
    "IN_JAIL": {
        "red_cube": {
            "pos": [-0.38338, 0.11101, 0.29],
            "ori": [3.14, 0.0, -1.57]
        },
        "green_cube": {
            "pos": [-0.32786, 0.10905, 0.29],
            "ori": [3.14, 0.0, -1.57]
        }
    },
    "ELECTRIC_COMPANY": {
        "red_cube": {
            "pos": [-0.26635, 0.10844, 0.29],
            "ori": [3.14, 0.0, 3.14]
        },
        "green_cube": {
            "pos": [-0.21752, 0.10905, 0.29],
            "ori": [3.14, 0.0, -3.14]
        }
    },
    "JEONJU": {
        "red_cube": {
            "pos": [-0.15167, 0.10844, 0.29],
            "ori": [3.14, 0.0, -3.14]
        },
        "green_cube": {
            "pos": [-0.09896, 0.10905, 0.29],
            "ori": [3.14, 0.0, -3.14]
        }
    },
    "DAEJEON": {
        "red_cube": {
            "pos": [-0.03404, 0.10844, 0.29],
            "ori": [3.14, 0.0, -3.14]
        },
        "green_cube": {
            "pos": [0.01564, 0.10905, 0.29],
            "ori": [3.14, 0.0, -3.14]
        }
    },
    "NON-FREE_PARKING": {
        "red_cube": {
            "pos": [0.07997, 0.10844, 0.29],
            "ori": [3.14, 0.0, 1.57]
        },
        "green_cube": {
            "pos": [0.13045, 0.10905, 0.29],
            "ori": [3.14, 0.0, 1.57]
        }
    },
    "BUSAN": {
        "red_cube": {
            "pos": [0.07997, 0.04156, 0.29],
            "ori": [3.14, 0.0, 1.57]
        },
        "green_cube": {
            "pos": [0.13045, 0.0405, 0.29],
            "ori": [3.14, 0.0, 1.57]
        }
    },
    "GYEONGJU": {
        "red_cube": {
            "pos": [0.07997, -0.02357, 0.29],
            "ori": [3.14, 0.0, 1.57]
        },
        "green_cube": {
            "pos": [0.13045, -0.02465, 0.29],
            "ori": [3.14, 0.0, 1.57]
        }
    },
    "GANGNEUNG": {
        "red_cube": {
            "pos": [0.07997, -0.08898, 0.29],
            "ori": [3.14, 0.0, 1.57]
        },
        "green_cube": {
            "pos": [0.13045, -0.08996, 0.29],
            "ori": [3.14, 0.0, 1.57]
        }
    },
    "GO_TO_JAIL": {
        "red_cube": {
            "pos": [0.07997, -0.1572, 0.29],
            "ori": [3.14, 0.0, 1.57]
        },
        "green_cube": {
            "pos": [0.13045, -0.15732, 0.29],
            "ori": [3.14, 0.0, 1.57]
        }
    },
    "DAEGU": {
        "red_cube": {
            "pos": [-0.03036, -0.1572, 0.29],
            "ori": [3.14, 0.0, -3.14]
        },
        "green_cube": {
            "pos": [0.02351, -0.15732, 0.29],
            "ori": [3.14, 0.0, -3.14]
        }
    },
    "CHANCE": {
        "red_cube": {
            "pos": [-0.14805, -0.1572, 0.29],
            "ori": [3.14, 0.0, -3.14]
        },
        "green_cube": {
            "pos": [-0.09401, -0.15732, 0.29],
            "ori": [3.14, 0.0, -3.14]
        }
    },
    "BUNDANG": {
        "red_cube": {
            "pos": [-0.26453, -0.1572, 0.29],
            "ori": [3.14, 0.0, -3.14]
        },
        "green_cube": {
            "pos": [-0.21345, -0.15732, 0.29],
            "ori": [3.14, 0.0, -3.14]
        }
    }
}

URL = "http://localhost:8000"

def move_base():
    absolute_joint_pose([0.0, 0.0, 0.5], [3.141, 0.0, -3.141])

# 6 motion movements
def absolute_cartesian_base(pos, ori):
    return requests.post(f"{URL}/api/move/absolute_cartesian_base", json={"pos": pos, "ori": ori}).json()

def relative_cartesian_base(pos, ori):
    return requests.post(f"{URL}/api/move/relative_cartesian_base", json={"pos": pos, "ori": ori}).json()

def relative_cartesian_tool(pos, ori):
    return requests.post(f"{URL}/api/move/relative_cartesian_tool", json={"pos": pos, "ori": ori}).json()

def absolute_joint_pose(pos, ori):
    return requests.post(f"{URL}/api/move/absolute_joint_pose", json={"pos": pos, "ori": ori}).json()

def joint_absolute(names, values):
    return requests.post(f"{URL}/api/move/joint_absolute", json={"joint_names": names, "joint_values": values}).json()

def joint_relative(names, values):
    return requests.post(f"{URL}/api/move/joint_relative", json={"joint_names": names, "joint_values": values}).json()

# 3 assistance functions
def gripper(close: bool):
    return requests.post(f"{URL}/api/services/gripper", json={"data": close}).json()

def get_eef_pose():
    return requests.get(f"{URL}/api/services/get_eef_pose").json()

def set_scales(vel, acc):
    return requests.post(f"{URL}/api/config/scales", json={"vel_scale": vel, "acc_scale": acc}).json()

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
        self.YOLO_offset_x: float = 0.009  # [m]
        self.YOLO_offset_y: float = -0.1   # [m]

        self.pos: Optional[dict] = None
        self.ori: Optional[dict] = None
        self.yaw: Optional[float] = None

    @staticmethod
    def _quaternion_to_yaw(qw: float, qx: float, qy: float, qz: float) -> float:
        siny_cosp = 2.0 * (qw * qz + qx * qy)
        cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
        return math.atan2(siny_cosp, cosy_cosp)

    @staticmethod
    def _init_move(target_object: str = "dice"):
        if target_object == "dice":
            absolute_cartesian_base([0.32040, -0.01058, 0.35], [3.141, 0.0, -3.141])
        else:
            # absolute_cartesian_base([-0.12857, 0.0, 0.3500], [3.141, 0.0, -3.141])
            absolute_cartesian_base([-0.12857, 0.035, 0.430], [3.141, 0.0, -3.141])

    @staticmethod
    def _toward_target(target_object: str = "dice", delay_exec: float = 0.2, target_pos: list = [0.0, 0.0, 0.0], target_ori: list = [0.0, 0.0, 0.0]):
        if target_object == "dice":
            absolute_cartesian_base(target_pos, target_ori)
        else:
            # Go upside of the piece
            target_pos[2] = target_pos[2] + 0.035
            absolute_cartesian_base(target_pos, target_ori)
            time.sleep(delay_exec)

            # Go down
            relative_cartesian_tool([0.0,0.0,0.05], [0.0,0.0,0.0])
    
    @staticmethod
    def _dest_move(target_object: str = "dice", delay_exec: float = 0.2, board_pos: str = "GO"):
        if target_object == "dice":
            # Go up
            relative_cartesian_tool([0.0,0.0,-0.1], [0.0,0.0,0.0])
            time.sleep(delay_exec)

            # place
            gripper(close=False)
            time.sleep(delay_exec)
        else:
            # Go up
            relative_cartesian_tool([0.0,0.0,-0.055], [0.0,0.0,0.0])
            time.sleep(delay_exec)

            # Go init move
            PnP._init_move("cube")
            time.sleep(delay_exec)

            # Go upper side of target pos.
            target_pos = board_positions[board_pos][target_object]["pos"]
            target_pos[2] = target_pos[2] + 0.035
            absolute_cartesian_base(target_pos, board_positions[board_pos][target_object]["ori"])
            time.sleep(delay_exec)

            # Go down
            relative_cartesian_tool([0.0,0.0,0.035], [0.0,0.0,0.0])
            time.sleep(delay_exec)

            # place
            gripper(close=False)
            time.sleep(delay_exec)

            # Go up and prepare to go init pos
            relative_cartesian_tool([0.0,0.0,-0.035], [0.0,0.0,0.0])
            time.sleep(delay_exec)

    def get_piece_info(self) -> bool:
        _target_object = self.TARGET_STR[self.target_num]

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

    def pick_and_place(self, board_pos: str = "GO"):
        if board_pos not in board_positions:
            raise ValueError(f"Unknown board_pos '{board_pos}'. Choose one of: {list(board_positions)}")

        gripper(close=False)
        # move to initial position

        self._init_move(self.target_object)
        time.sleep(self.delay_exec)
        
        # For YOLO, we need to set offset
        if self.is_YOLO:
            self.pos['x'] += self.YOLO_offset_x
            self.pos['y'] += self.YOLO_offset_y
        else:
            # This is for dice.
            if self.target_object == "dice":
                yaw_status = self._checking_yaw(self.yaw)
                print(self.yaw)
                self.converting_yaw(yaw_status=yaw_status, target_yaw_status=2)
            # This is for piece pnp.
            else:
                yaw_status = self._checking_yaw(self.yaw)
                # clockwisely rotate 90 degree.
                if board_pos in ("GO", "SUWON", "SEOUL", "INCHEON_AIRPORT", "IN_JAIL"):
                    self.converting_yaw(yaw_status=yaw_status, target_yaw_status=1)

                # Counter clockwisely rotate -90 degree.
                elif board_pos in ("NON-FREE_PARKING", "BUSAN", "GYEONGJU", "GANGNEUNG", "GO_TO_JAIL"):
                    self.converting_yaw(yaw_status=yaw_status, target_yaw_status=3)

                # Rotate 180 degree. Looking front side.
                else:
                    self.converting_yaw(yaw_status=yaw_status, target_yaw_status=2)

        logger.info(f"{self.target_object}: x={self.pos['x']}, y={self.pos['y']}, z={self.pos['z']}, yaw={self.yaw}")

        # move toward target
        target_pos = [self.pos['y'], -self.pos['x'], 0.29]
        target_ori = [3.14, 0.0, self.yaw]
        print(self.yaw)
        self._toward_target(self.target_object, self.delay_exec, target_pos, target_ori)
        time.sleep(self.delay_exec)

        # grasp
        gripper(close=True)
        time.sleep(self.delay_exec)

        # move to destination
        self._dest_move(self.target_object, self.delay_exec, board_pos)
        time.sleep(self.delay_exec)





def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    # init
    move_base()
    time.sleep(2.0)
    pnp = PnP(target_object=sys.argv[1], is_YOLO=False, delay_exec=2.0)

    # pick and place
    if not pnp.get_piece_info():
        logger.error("Failed to get piece info, aborting.")
        return
    pnp.pick_and_place(board_pos=sys.argv[2])


if __name__ == "__main__":
    main()
