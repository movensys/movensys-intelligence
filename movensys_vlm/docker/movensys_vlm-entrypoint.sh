#!/bin/bash
set -e

source /opt/ros/${ROS_DISTRO}/setup.bash

WS=/app/movensys_ws

if [ -d "${WS}/src/movensys-manipulator" ]; then
    echo "=== Building movensys_manipulator_moveit_config ==="
    cd ${WS}
    colcon build \
        --packages-select movensys_manipulator_moveit_config \
        --build-base ${WS}/build \
        --install-base ${WS}/install \
        --symlink-install \
        2>&1
    source ${WS}/install/setup.bash
    echo "=== Build complete ==="
else
    echo "WARNING: ${WS}/src/movensys-manipulator not found, skipping build"
fi

cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8000
