#!/bin/bash
set -e

# ROS 2 environment is sourced even at M0 so ros2_node.py can be added
# in M4 without changing this file.
source /opt/ros/${ROS_DISTRO}/setup.bash

cd /app
exec uvicorn main:app --host 0.0.0.0 --port "${MONOPOLY_PORT:-8000}"
