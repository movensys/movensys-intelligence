# MOVENSYS VLM Manipulator

MOVENSYS provides a Vision Language Model (VLM) demo for controlling the CR3A manipulator via natural language, powered by Intel Edge AI.

AI models (Qwen, Whisper) are accelerated and optimized by OpenVINO for Intel CPU, iGPU, iNPU.

## Repository Structure

```
movensys_vlm_manipulator/
├── movensys_intel_manipulator/   # Submodule — robot description + MoveIt2 config
│   ├── movensys_manipulator_description/   # URDF/xacro, launch, meshes
│   └── movensys_manipulator_moveit_config/ # MoveIt2 config, moveit2_client C++ library
├── movensys_vlm_bridge/          # ROS2 bridge between VLM demo and MoveIt2
│   ├── srv/                      # Service definitions (1:1 with C++ methods)
│   ├── src/vlm_bridge_node.cpp   # Bridge node
│   └── launch/
├── vlm-demo-so101/               # Submodule — Intel Edge AI demo (web UI, backend)
├── patch/                        # Patches applied to vlm-demo-so101 for ROS2
│   ├── vlm-demo-so101/apps/platforms/cr3a/sdk.py   # Python SDK (service client)
│   ├── vlm-demo-so101/apps/utils/platform.py       # Platform wrapper
│   ├── vlm-demo-so101/apps/server.py               # FastAPI + MCP tools
│   └── vlm-demo-so101/ui/src/lib/langchain.ts      # LangChain agent config
├── setup.sh                      # Full setup script
└── doc/                          # Run instructions
```

## Architecture

```
Web UI (Next.js, port 3000)
  ↓  LangChain + MCP
FastAPI Server (port 8081)
  ↓  MCP tools call Python SDK
CR3A SDK (rclpy service clients)
  ↓  ROS2 services
vlm_bridge_node (C++)
  ↓  MoveIt2Client C++ library
move_group (MoveIt2)
  ↓
Gazebo / Real Robot
```

The VLM demo does **not** call MoveIt API directly. All motion commands go through `vlm_bridge_node`, which wraps the C++ `MoveIt2Client` library from `movensys_intel_manipulator`.

## VLM Bridge — API Reference

The bridge exposes one ROS2 service per C++ `MoveIt2Client` method.
Field names match the C++ `PoseTarget` (`pos[3]`, `ori[3]`) and `TFResult` structs.

| C++ Method | ROS2 Service | Request Fields |
|---|---|---|
| `absoluteBaseEefCartesian(PoseTarget)` | `~/absolute_base_eef_cartesian` | `pos[3]`, `ori[3]` |
| `absoluteBaseEefJointMovement(PoseTarget)` | `~/absolute_base_eef_joint_movement` | `pos[3]`, `ori[3]` |
| `relativeBaseEefCartesian(PoseTarget)` | `~/relative_base_eef_cartesian` | `pos[3]`, `ori[3]` |
| `relativeToolEefCartesian(PoseTarget)` | `~/relative_tool_eef_cartesian` | `pos[3]`, `ori[3]` |
| `jointMovement(map<string,double>)` | `~/joint_movement` | `joint_names[]`, `joint_targets[]` |
| `getCurrentEefPose() → TFResult` | `~/get_current_eef_pose` | — (response: `x,y,z,roll,pitch,yaw,qx,qy,qz,qw`) |
| `setGripper(bool)` | `~/set_gripper` | `std_srvs/SetBool` |

## MCP Tools (LLM-callable)

These are exposed to the LangChain agent via FastMCP:

| MCP Tool | Bridge Service Used | Description |
|---|---|---|
| `move_arm` | `absoluteBaseEefCartesian` / `jointMovement` | Named pose or absolute Cartesian move |
| `move_arm_joint_planning` | `absoluteBaseEefJointMovement` | Absolute Cartesian via joint planning |
| `relative_move_base` | `relativeBaseEefCartesian` | Relative move in base frame |
| `relative_move_tool` | `relativeToolEefCartesian` | Relative move in tool frame |
| `move_joints` | `jointMovement` | Direct joint angle control |
| `get_arm_pose` | `getCurrentEefPose` | Query current EEF position |
| `set_gripper` | `setGripper` | Open/close gripper |
| `pickup_object` | Multiple services | Detect, analyze, and pick up object |
| `describe_scene` | — (VLM only) | Describe camera view |

## Moving the CR3A in Gazebo

Once all terminals are running (see `doc/stage1a_vlm_simulation.md`), open the web UI at **http://localhost:3000**.

Use the chat interface to control the CR3A arm with natural language:

### 5 Basic Movements

| # | Movement Type | MCP Tool | Example chat message |
|---|---|---|---|
| 1 | absoluteBaseEefCartesian | `move_arm` | `Move the arm to x=0.3, y=0.0, z=0.4` |
| 2 | absoluteBaseEefJointMovement | `move_arm_joint_planning` | `Move to x=0.3, y=0.0, z=0.4 using joint planning` |
| 3 | relativeBaseEefCartesian | `relative_move_base` | `Move 10cm forward in the base frame` |
| 4 | relativeToolEefCartesian | `relative_move_tool` | `Move 5cm down in the tool frame` |
| 5 | jointMovement | `move_joints` | `Set joint1 to 1.0 radians` |

### Other Commands

| Goal | Example chat message |
|------|----------------------|
| Move to named pose | `Move the arm to home` or `Move the arm to container` |
| Get current position | `Where is the arm?` |

<!-- 
Not supported features now.
| Open/close gripper | `Open the gripper` |
| Pick up an object | `Pick up the red box` |
| Describe what the camera sees | `Describe the scene` |
-->

## Setup

```bash
./setup.sh
```

See `doc/stage1a_vlm_simulation.md` for step-by-step run instructions.
