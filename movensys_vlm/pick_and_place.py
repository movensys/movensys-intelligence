import logging
import math
import sys
import time
import requests
from typing import Optional

logger = logging.getLogger(__name__)

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
    def __init__(self, target_object: str = "red_cube", is_YOLO: bool = True, delay_exec: float = 0.2):
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
            absolute_cartesian_base([-0.24, -0.1, 0.47], [3.141, 0.0, -3.141])
        else:
            absolute_cartesian_base([-0.24, -0.1, 0.47], [3.141, 0.0, -3.141])

    @staticmethod
    def _dest_move(target_object: str = "dice"):
        if target_object == "dice":
            relative_cartesian_base([0.0,0.0,-0.18], [0.0,0.0,0.0])
        else:
            # Need to define 16 types of position in IsaacSim.
            time.sleep(0.01)

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
            self.pos = {"x": tf["translation"]["x"], "y": tf["translation"]["y"], "z": tf["translation"]["z"]}
            self.ori = {"w": tf["rotation"]["w"], "x": tf["rotation"]["x"], "y": tf["rotation"]["y"], "z": tf["rotation"]["z"]}

        # Isaac
        else:
            URL_topic = f"{URL}/api/topics/{_target_object}"
            resp = requests.get(URL_topic)
            info = resp.json()
            self.pos = {"x": info["position"]["x"], "y": info["position"]["y"], "z": info["position"]["z"]}
            self.ori = {"w": info["orientation"]["w"], "x": info["orientation"]["x"], "y": info["orientation"]["y"], "z": info["orientation"]["z"]}

        self.yaw = self._quaternion_to_yaw(self.ori["w"], self.ori["x"], self.ori["y"], self.ori["z"])
        return True

    def pick_and_place(self):
        # move to initial position
        self._init_move(self.target_object)
        time.sleep(self.delay_exec)

        # For YOLO, we need to set offset
        if self.is_YOLO:
            self.pos["x"] += self.YOLO_offset_x
            self.pos["y"] += self.YOLO_offset_y
        logger.info(f"{self.target_object}: x={self.pos['x']}, y={self.pos['y']}, z={self.pos['z']}, yaw={self.yaw}")

        # move toward target
        relative_cartesian_tool([self.pos["x"], self.pos["y"], 0.18],[0.0, 0.0, self.yaw])
        time.sleep(self.delay_exec)

        # grasp
        gripper(close=True)
        time.sleep(self.delay_exec)
        
        # move to destination
        self._dest_move(self.target_object)
        time.sleep(self.delay_exec)
        
        # place
        gripper(close=False)
        time.sleep(self.delay_exec)



def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    # init
    move_base()
    pnp = PnP(target_object = sys.argv[1], is_YOLO=False, delay_exec=0.2)
    
    # pick and place
    if not pnp.get_piece_info():
        logger.error("Failed to get piece info, aborting.")
        return
    pnp.pick_and_place()


if __name__ == "__main__":
    main()
