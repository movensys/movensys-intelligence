"""ROS 2 side of movensys_push_t: robot state, the top camera and the MoveIt2 move services.

The camera is the 9a scene's /World/camera_top_link (RSD455): /image_top/{rgb,camera_info} (depth not used),
frame camera_top_color_optical_frame.

Trimmed from movensys_vlm/ros2_node.py: no gripper (dobot_cr3a_custom_tool is a rigid tool), no
board / dice / YOLO topics and no Isaac object teleports.
"""

import base64
import threading
import time
from typing import Optional

import cv2
import geometry_msgs.msg
import numpy as np
import rclpy
import sensor_msgs.msg
import tf2_msgs.msg
from fastapi import HTTPException
from movensys_manipulator_moveit_config.srv import GetEefPose, MoveJoints, MovePose
from rcl_interfaces.msg import Parameter, ParameterType
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy, qos_profile_sensor_data

import imitation_core as ic


# Newest top-camera frames (RGB uint8), shared with imitation_node. The image callback only
# decodes into this ring buffer; JPEG for the web UI is encoded on demand from the newest frame,
# so a slow consumer skips frames instead of serving an old one.
frames = ic.FrameBuffer(size=4)
_jpeg_lock = threading.Lock()
_jpeg_cache: dict = {"seq": -1, "value": None}


def latest_rgb_jpeg() -> Optional[dict]:
    """Newest frame as base64 JPEG (cached per frame)."""
    f = frames.latest()
    if f is None:
        return None
    seq, t_rx, _, img = f
    with _jpeg_lock:
        if _jpeg_cache["seq"] != seq:
            _, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
            _jpeg_cache["seq"] = seq
            _jpeg_cache["value"] = {
                "data": base64.b64encode(buf.tobytes()).decode("utf-8"),
                "encoding": "jpeg",
                "width": int(img.shape[1]),
                "height": int(img.shape[0]),
                "seq": seq,
            }
        value = dict(_jpeg_cache["value"])
    value["age"] = round(time.monotonic() - t_rx, 3)
    return value


def _camera_info_to_dict(msg: sensor_msgs.msg.CameraInfo) -> dict:
    return {
        "width": msg.width,
        "height": msg.height,
        "distortion_model": msg.distortion_model,
        "k": list(msg.k),
        "d": list(msg.d),
        "r": list(msg.r),
        "p": list(msg.p),
        "binning_x": msg.binning_x,
        "binning_y": msg.binning_y,
    }


class PushTNode(Node):
    _TF_PARENT = "world_manipulator"
    _TF_CHILD = "camera_top_color_optical_frame"

    def __init__(self):
        super().__init__("movensys_push_t_api")
        cb = ReentrantCallbackGroup()

        self.latest_eef_pose: Optional[dict] = None
        self.latest_eef_rpy: Optional[dict] = None
        self.latest_joint_states: Optional[dict] = None
        self.latest_top_camera_info: Optional[dict] = None
        self.latest_tf_static: Optional[dict] = None

        transient_local = QoSProfile(
            depth=1,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            reliability=QoSReliabilityPolicy.RELIABLE,
        )

        def sub(msg_type, topic, attr, convert, qos=10):
            def _cb(msg):
                setattr(self, attr, convert(msg))
            self.create_subscription(msg_type, topic, _cb, qos, callback_group=cb)

        sub(geometry_msgs.msg.PoseStamped, "/wmx/moveit2/eef_pose", "latest_eef_pose", self._pose_stamped)
        sub(geometry_msgs.msg.Vector3Stamped, "/wmx/moveit2/eef_rpy", "latest_eef_rpy",
            lambda m: {"roll": m.vector.x, "pitch": m.vector.y, "yaw": m.vector.z})
        sub(sensor_msgs.msg.JointState, "/joint_states", "latest_joint_states",
            lambda m: {"name": list(m.name), "position": list(m.position),
                       "velocity": list(m.velocity), "effort": list(m.effort)})
        sub(sensor_msgs.msg.CameraInfo, "/image_top/camera_info", "latest_top_camera_info", _camera_info_to_dict)
        self.create_subscription(sensor_msgs.msg.Image, "/image_top/rgb", self._cb_image,
                                 qos_profile_sensor_data, callback_group=MutuallyExclusiveCallbackGroup())
        self.create_subscription(tf2_msgs.msg.TFMessage, "/tf_static", self._cb_tf_static,
                                 transient_local, callback_group=cb)

        self.cli_get_eef_pose = self.create_client(GetEefPose, "/wmx/moveit2/get_eef_pose", callback_group=cb)
        self.cli_abs_base_cart = self.create_client(MovePose, "/wmx/moveit2/absolute_base_eef_cartesian", callback_group=cb)
        self.cli_rel_base_cart = self.create_client(MovePose, "/wmx/moveit2/relative_base_eef_cartesian", callback_group=cb)
        self.cli_rel_tool_cart = self.create_client(MovePose, "/wmx/moveit2/relative_tool_eef_cartesian", callback_group=cb)
        self.cli_abs_base_joint = self.create_client(MovePose, "/wmx/moveit2/absolute_base_eef_joint_movement", callback_group=cb)
        self.cli_joint_abs = self.create_client(MoveJoints, "/wmx/moveit2/joint_movement", callback_group=cb)
        self.cli_joint_rel = self.create_client(MoveJoints, "/wmx/moveit2/relative_joint_movement", callback_group=cb)
        self.cli_set_params = self.create_client(SetParameters, "/trajectory_api/set_parameters", callback_group=cb)
        self.cli_get_params = self.create_client(GetParameters, "/trajectory_api/get_parameters", callback_group=cb)

    @property
    def latest_top_rgb_image(self) -> Optional[dict]:
        return latest_rgb_jpeg()

    def _cb_image(self, msg: sensor_msgs.msg.Image):
        try:
            img = ic.decode_image(msg.data, msg.width, msg.height, msg.step, msg.encoding)
        except ValueError:
            return
        frames.put(img, time.monotonic(), msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)

    @staticmethod
    def _pose_stamped(msg: geometry_msgs.msg.PoseStamped) -> dict:
        p, o = msg.pose.position, msg.pose.orientation
        return {
            "position": {"x": p.x, "y": p.y, "z": p.z},
            "orientation": {"x": o.x, "y": o.y, "z": o.z, "w": o.w},
        }

    def _cb_tf_static(self, msg: tf2_msgs.msg.TFMessage):
        for t in msg.transforms:
            if t.header.frame_id != self._TF_PARENT or t.child_frame_id != self._TF_CHILD:
                continue
            tr, ro = t.transform.translation, t.transform.rotation
            self.latest_tf_static = {
                "parent_frame": t.header.frame_id,
                "child_frame": t.child_frame_id,
                "translation": {"x": tr.x, "y": tr.y, "z": tr.z},
                "rotation": {"x": ro.x, "y": ro.y, "z": ro.z, "w": ro.w},
            }
            break


ros_node: Optional[PushTNode] = None
imitation_node = None  # imitation_node.ImitationNode


def require_node() -> PushTNode:
    if ros_node is None:
        raise HTTPException(503, detail="ROS node not running")
    return ros_node


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
    node = require_node()
    req = GetParameters.Request()
    req.names = ["vel_scale", "acc_scale"]
    values = call_service(node.cli_get_params, req).values

    def as_double(v):
        return v.double_value if v.type == ParameterType.PARAMETER_DOUBLE else 0.3

    return {"vel_scale": as_double(values[0]), "acc_scale": as_double(values[1])}


def set_scales(vel_scale: float, acc_scale: float) -> dict:
    node = require_node()
    params = []
    for name, value in (("vel_scale", vel_scale), ("acc_scale", acc_scale)):
        p = Parameter()
        p.name = name
        p.value.type = ParameterType.PARAMETER_DOUBLE
        p.value.double_value = float(value)
        params.append(p)
    req = SetParameters.Request()
    req.parameters = params
    resp = call_service(node.cli_set_params, req)
    return {"success": all(r.successful for r in resp.results), "vel_scale": vel_scale, "acc_scale": acc_scale}


def start_ros_node():
    def _spin():
        global ros_node, imitation_node
        from imitation_node import ImitationNode

        rclpy.init()
        ros_node = PushTNode()
        imitation_node = ImitationNode(frames, lambda: ros_node.latest_top_camera_info)
        executor = MultiThreadedExecutor(num_threads=8)
        executor.add_node(ros_node)
        executor.add_node(imitation_node)
        try:
            executor.spin()
        finally:
            imitation_node.destroy_node()
            ros_node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()

    threading.Thread(target=_spin, daemon=True).start()
    time.sleep(1.0)
