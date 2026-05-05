import logging
import math
import time
import requests

URL = "http://localhost:8000"
STALE_SECONDS = 2.0
_YOLO = ("yolo_cube_red", "yolo_cube_green", "dice")
# yolo_offset_x = 0.015  # [m]
# yolo_offset_y = -0.075  # [m]
yolo_offset_x = 0.009  # [m]
yolo_offset_y = -0.1  # [m]

logger = logging.getLogger(__name__)

def quaternion_to_yaw(qw : float, qx : float, qy : float, qz : float) -> float:
    siny_cosp = 2.0 * (qw*qz + qx*qy)
    cosy_cosp = 1.0 - 2.0 * (qy*qy + qz*qz)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return yaw

def get_piece_yolo(name: str = _YOLO[0]):
    """Single-shot read. Returns [translation, rotation] (each a dict) or None on miss/stale."""
    resp = requests.get(f"{URL}/api/topics/yolo_tf")
    if resp.status_code == 503:
        logger.info("YOLO /tf unavailable: %s", resp.json().get("detail", ""))
        return None
    resp.raise_for_status()
    tf_all = resp.json()
    if name not in tf_all:
        logger.info("%s not detected (have: %s)", name, list(tf_all))
        return None
    tf = tf_all[name]
    age = time.time() - tf["received_at"]
    if age > STALE_SECONDS:
        logger.info("%s is stale (%.2fs old)", name, age)
        return None
    return [tf["translation"], tf["rotation"]]


# def get_piece_pose(idx: int):
#     """Read /piece_{idx} pose from the ROS2 topic via REST.
#     Returns [position, orientation] (each a dict) or None if unavailable."""
#     resp = requests.get(f"{URL}/api/topics/piece_{idx}")
#     if resp.status_code == 503:
#         logger.info("/piece_%d unavailable: %s", idx, resp.json().get("detail", ""))
#         return None
#     resp.raise_for_status()
#     pose = resp.json()
#     return [pose["position"], pose["orientation"]]


# def get_dice_pos():
#     """Read dice position from yolo_tf (frame 'yolo_dice_one').
#     Returns [translation, rotation] (each a dict) or None if unavailable/stale."""
#     return get_piece_yolo("yolo_dice_one")


def get_piece_xyz_yaw(name: str = _YOLO[0], decimal_place: int = 4):
    """Single-shot read. Returns [x, y, z, yaw] rounded to `decimal_place`, or None on miss/stale."""
    result = get_piece_yolo(name)
    if result is None:
        raise RuntimeError(f"get_piece_xyz_yaw({name}): no valid sample")
    t, r = result
    yaw = quaternion_to_yaw(r["w"], r["x"], r["y"], r["z"])
    return [round(v, decimal_place) for v in (t["x"], t["y"], t["z"], yaw)]

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
    return requests.post(f"{URL}/api/config/scales",
                        json={"vel_scale": vel, "acc_scale": acc}).json()

def init(status="dice"):
    # dice init 
    absolute_joint_pose([-0.24, -0.1, 0.47], [3.141, 0.0, -3.141]) if status == "dice" else None

def pick_and_place(name: str = _YOLO[0]) -> None:
    gripper(close=False)
    x, y, z, yaw = get_piece_xyz_yaw(name)
    print(f"{name}: x={x}, y={y}, z={z}, yaw={yaw}")
    x = x + yolo_offset_x
    y = y + yolo_offset_y
    print(f"{name}: x={x}, y={y}, z={z}, yaw={yaw}")

    relative_cartesian_tool([x,y, 0.18], [0.0,0.0,yaw])
    time.sleep(2.0)
    gripper(close=True)
    time.sleep(2.0)
    absolute_joint_pose([-0.24, -0.1, 0.47], [3.141, 0.0, -3.141])
    time.sleep(1.0)
    gripper(close=False)
    time.sleep(3.0)
    init(status="dice")

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    absolute_joint_pose([-0.0, -0.0, 0.5], [3.141, 0.0, -3.141])
    init()
    time.sleep(3.0)
    pick_and_place(_YOLO[2])
    


if __name__ == "__main__":
    main()
