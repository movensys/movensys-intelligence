import base64
import threading
import time
from typing import Optional

import numpy as np
import cv2
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
import geometry_msgs.msg
import sensor_msgs.msg
import std_srvs.srv
import tf2_msgs.msg
from rcl_interfaces.srv import SetParameters, GetParameters
from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType
from movensys_manipulator_moveit_config.srv import GetEefPose, MovePose, MoveJoints
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy

from fastapi import HTTPException


def _encode_depth(msg: sensor_msgs.msg.Image) -> Optional[dict]:
    """Convert 32FC1 depth image to base64-encoded colorized JPEG (turbo colormap, 0.1–5 m)."""
    try:
        depth = np.frombuffer(bytes(msg.data), dtype=np.float32).reshape(msg.height, msg.width)
        valid = (depth > 0.1) & (depth < 5.0)
        depth_norm = np.zeros_like(depth, dtype=np.uint8)
        depth_norm[valid] = ((depth[valid] - 0.1) / 4.9 * 255).astype(np.uint8)
        colored = cv2.applyColorMap(depth_norm, cv2.COLORMAP_TURBO)
        colored[~valid] = (0, 0, 0)
        _, buf = cv2.imencode('.jpg', colored, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return {
            "data": base64.b64encode(buf.tobytes()).decode('utf-8'),
            "encoding": "jpeg_turbo_0.1-5m",
            "width": msg.width,
            "height": msg.height,
        }
    except Exception:
        return None


def _encode_rgb(msg: sensor_msgs.msg.Image) -> Optional[dict]:
    """Convert RGB8 image to base64-encoded JPEG."""
    try:
        img = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(msg.height, msg.width, 3)
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return {
            "data": base64.b64encode(buf.tobytes()).decode('utf-8'),
            "encoding": "jpeg",
            "width": msg.width,
            "height": msg.height,
        }
    except Exception:
        return None


class ManipulatorNode(Node):
    def __init__(self):
        super().__init__("movensys_vlm_api")
        cb = ReentrantCallbackGroup()

        self.latest_eef_pose: Optional[dict] = None
        self.latest_eef_rpy: Optional[dict] = None
        self.latest_joint_states: Optional[dict] = None
        self.latest_top_camera_info: Optional[dict] = None
        self.latest_top_depth_image: Optional[dict] = None
        self.latest_top_rgb_image: Optional[dict] = None
        self.latest_hand_camera_info: Optional[dict] = None
        self.latest_hand_depth_image: Optional[dict] = None
        self.latest_hand_rgb_image: Optional[dict] = None
        self.latest_tf_static: Optional[dict] = None
        self.latest_board_pose: Optional[dict] = None
        self.latest_piece_1_pose: Optional[dict] = None
        self.latest_piece_2_pose: Optional[dict] = None

        _transient_local = QoSProfile(
            depth=1,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            reliability=QoSReliabilityPolicy.RELIABLE,
        )

        self.create_subscription(geometry_msgs.msg.PoseStamped,   "/wmx/moveit2/eef_pose", self._cb_eef_pose,      10, callback_group=cb)
        self.create_subscription(geometry_msgs.msg.Vector3Stamped, "/wmx/moveit2/eef_rpy",  self._cb_eef_rpy,       10, callback_group=cb)
        self.create_subscription(sensor_msgs.msg.JointState,       "/joint_states",          self._cb_joint_states,  10, callback_group=cb)
        self.create_subscription(sensor_msgs.msg.CameraInfo,       "/image_top/camera_info",  self._cb_camera_info,       10, callback_group=cb)
        self.create_subscription(sensor_msgs.msg.Image,            "/image_top/depth",        self._cb_depth,              1, callback_group=cb)
        self.create_subscription(sensor_msgs.msg.Image,            "/image_top/rgb",          self._cb_rgb,                1, callback_group=cb)
        self.create_subscription(sensor_msgs.msg.CameraInfo,       "/image_hand/camera_info", self._cb_hand_camera_info,  10, callback_group=cb)
        self.create_subscription(sensor_msgs.msg.Image,            "/image_hand/depth",       self._cb_hand_depth,         1, callback_group=cb)
        self.create_subscription(sensor_msgs.msg.Image,            "/image_hand/rgb",         self._cb_hand_rgb,           1, callback_group=cb)
        self.create_subscription(tf2_msgs.msg.TFMessage,           "/tf_static",              self._cb_tf_static,          _transient_local, callback_group=cb)
        self.create_subscription(geometry_msgs.msg.Pose,           "/board",                  self._cb_board_pose,        10, callback_group=cb)
        self.create_subscription(geometry_msgs.msg.Pose,           "/piece_1",                self._cb_piece_1_pose,      10, callback_group=cb)
        self.create_subscription(geometry_msgs.msg.Pose,           "/piece_2",                self._cb_piece_2_pose,      10, callback_group=cb)

        self.cli_get_eef_pose   = self.create_client(GetEefPose,           "/wmx/moveit2/get_eef_pose",                     callback_group=cb)
        self.cli_gripper        = self.create_client(std_srvs.srv.SetBool, "/wmx/set_gripper",                              callback_group=cb)
        self.cli_abs_base_cart  = self.create_client(MovePose,             "/wmx/moveit2/absolute_base_eef_cartesian",      callback_group=cb)
        self.cli_rel_base_cart  = self.create_client(MovePose,             "/wmx/moveit2/relative_base_eef_cartesian",      callback_group=cb)
        self.cli_rel_tool_cart  = self.create_client(MovePose,             "/wmx/moveit2/relative_tool_eef_cartesian",      callback_group=cb)
        self.cli_abs_base_joint = self.create_client(MovePose,             "/wmx/moveit2/absolute_base_eef_joint_movement", callback_group=cb)
        self.cli_joint_abs      = self.create_client(MoveJoints,           "/wmx/moveit2/joint_movement",                   callback_group=cb)
        self.cli_joint_rel      = self.create_client(MoveJoints,           "/wmx/moveit2/relative_joint_movement",          callback_group=cb)
        self.cli_set_params     = self.create_client(SetParameters,        "/moveit2_api_node/set_parameters",              callback_group=cb)
        self.cli_get_params     = self.create_client(GetParameters,        "/moveit2_api_node/get_parameters",              callback_group=cb)

    def _cb_eef_pose(self, msg: geometry_msgs.msg.PoseStamped):
        p, o = msg.pose.position, msg.pose.orientation
        self.latest_eef_pose = {
            "position":    {"x": p.x, "y": p.y, "z": p.z},
            "orientation": {"x": o.x, "y": o.y, "z": o.z, "w": o.w},
        }

    def _cb_eef_rpy(self, msg: geometry_msgs.msg.Vector3Stamped):
        v = msg.vector
        self.latest_eef_rpy = {"roll": v.x, "pitch": v.y, "yaw": v.z}

    def _cb_joint_states(self, msg: sensor_msgs.msg.JointState):
        self.latest_joint_states = {
            "name":     list(msg.name),
            "position": list(msg.position),
            "velocity": list(msg.velocity),
            "effort":   list(msg.effort),
        }

    def _cb_camera_info(self, msg: sensor_msgs.msg.CameraInfo):
        self.latest_top_camera_info = {
            "width":             msg.width,
            "height":            msg.height,
            "distortion_model":  msg.distortion_model,
            "k":                 list(msg.k),
            "d":                 list(msg.d),
            "r":                 list(msg.r),
            "p":                 list(msg.p),
            "binning_x":         msg.binning_x,
            "binning_y":         msg.binning_y,
        }

    def _cb_depth(self, msg: sensor_msgs.msg.Image):
        self.latest_top_depth_image = _encode_depth(msg)

    def _cb_rgb(self, msg: sensor_msgs.msg.Image):
        self.latest_top_rgb_image = _encode_rgb(msg)

    def _cb_hand_camera_info(self, msg: sensor_msgs.msg.CameraInfo):
        self.latest_hand_camera_info = {
            "width":             msg.width,
            "height":            msg.height,
            "distortion_model":  msg.distortion_model,
            "k":                 list(msg.k),
            "d":                 list(msg.d),
            "r":                 list(msg.r),
            "p":                 list(msg.p),
            "binning_x":         msg.binning_x,
            "binning_y":         msg.binning_y,
        }

    def _cb_hand_depth(self, msg: sensor_msgs.msg.Image):
        self.latest_hand_depth_image = _encode_depth(msg)

    def _cb_hand_rgb(self, msg: sensor_msgs.msg.Image):
        self.latest_hand_rgb_image = _encode_rgb(msg)

    @staticmethod
    def _pose_to_dict(msg: geometry_msgs.msg.Pose) -> dict:
        p, o = msg.position, msg.orientation
        return {
            "position":    {"x": p.x, "y": p.y, "z": p.z},
            "orientation": {"x": o.x, "y": o.y, "z": o.z, "w": o.w},
        }

    def _cb_board_pose(self, msg: geometry_msgs.msg.Pose):
        self.latest_board_pose = self._pose_to_dict(msg)

    def _cb_piece_1_pose(self, msg: geometry_msgs.msg.Pose):
        self.latest_piece_1_pose = self._pose_to_dict(msg)

    def _cb_piece_2_pose(self, msg: geometry_msgs.msg.Pose):
        self.latest_piece_2_pose = self._pose_to_dict(msg)

    _TF_PARENT = "world_manipulator"
    _TF_CHILD  = "camera_top_color_optical_frame"

    def _cb_tf_static(self, msg: tf2_msgs.msg.TFMessage):
        for t in msg.transforms:
            if t.header.frame_id != self._TF_PARENT or t.child_frame_id != self._TF_CHILD:
                continue
            tr = t.transform.translation
            ro = t.transform.rotation
            self.latest_tf_static = {
                "parent_frame": t.header.frame_id,
                "child_frame":  t.child_frame_id,
                "translation":  {"x": tr.x, "y": tr.y, "z": tr.z},
                "rotation":     {"x": ro.x, "y": ro.y, "z": ro.z, "w": ro.w},
            }
            break


ros_node: Optional[ManipulatorNode] = None


def call_service(client, request, timeout: float = 30.0):
    if not client.wait_for_service(timeout_sec=5.0):
        raise HTTPException(503, detail=f"Service {client.srv_name} not available")
    future = client.call_async(request)
    deadline = time.monotonic() + timeout
    while not future.done():
        if time.monotonic() > deadline:
            raise HTTPException(504, detail=f"Service {client.srv_name} timed out")
        time.sleep(0.01)
    if future.exception():
        raise HTTPException(502, detail=str(future.exception()))
    return future.result()


def get_scales() -> dict:
    if ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    req = GetParameters.Request()
    req.names = ["vel_scale", "acc_scale"]
    resp = call_service(ros_node.cli_get_params, req)
    values = resp.values
    return {
        "vel_scale": values[0].double_value if values[0].type == ParameterType.PARAMETER_DOUBLE else 0.3,
        "acc_scale": values[1].double_value if values[1].type == ParameterType.PARAMETER_DOUBLE else 0.3,
    }


def set_scales(vel_scale: float, acc_scale: float) -> dict:
    if ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    req = SetParameters.Request()
    p_vel = Parameter()
    p_vel.name = "vel_scale"
    p_vel.value.type = ParameterType.PARAMETER_DOUBLE
    p_vel.value.double_value = float(vel_scale)
    p_acc = Parameter()
    p_acc.name = "acc_scale"
    p_acc.value.type = ParameterType.PARAMETER_DOUBLE
    p_acc.value.double_value = float(acc_scale)
    req.parameters = [p_vel, p_acc]
    resp = call_service(ros_node.cli_set_params, req)
    success = all(r.successful for r in resp.results)
    return {"success": success, "vel_scale": vel_scale, "acc_scale": acc_scale}


def start_ros_node():
    def _spin():
        global ros_node
        rclpy.init()
        ros_node = ManipulatorNode()
        executor = MultiThreadedExecutor()
        executor.add_node(ros_node)
        try:
            executor.spin()
        finally:
            ros_node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()

    threading.Thread(target=_spin, daemon=True).start()
    time.sleep(1.0)
