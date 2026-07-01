#!/bin/bash
set -e

# ROS 2 environment is sourced even at M0 so ros2_node.py can be added
# in M4 without changing this file.
source /opt/ros/${ROS_DISTRO}/setup.bash

cd /app
# Bind loopback only — getUserMedia() requires a secure context, and
# `http://0.0.0.0:*` / `http://<lan-ip>:*` are non-secure origins, so
# the browser would block microphone access. `127.0.0.1` (localhost)
# is treated as secure. network_mode: host in compose makes this port
# reachable on the host's loopback exactly the same way.
exec uvicorn main:app --host 127.0.0.1 --port "${MONOPOLY_PORT:-7999}"
