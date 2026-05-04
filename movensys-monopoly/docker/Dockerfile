ARG ROS_DISTRO=jazzy
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO

USER root

# Use https mirrors (matches movensys_vlm)
RUN rm -f /etc/apt/sources.list.d/yarn.list || true
RUN if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
      sed -i -E 's|http://(archive\|security)\.ubuntu\.com/ubuntu/|https://\1.ubuntu.com/ubuntu/|g' \
        /etc/apt/sources.list.d/ubuntu.sources; \
    fi

# M0: Python tooling + cyclonedds RMW (the rest of the movensys stack
# uses RMW_IMPLEMENTATION=rmw_cyclonedds_cpp, so we ship it here too
# to avoid rcl aborting the process when the shared lib is missing).
# M4: python3-opencv + sensor_msgs are needed for ros2_node.py to
# subscribe to /image_{top,hand}/* and encode RGB/depth as JPEG for the
# browser WS proxy (§11.5). sensor_msgs is already in ros-base; we add
# opencv (brings numpy as a dep) and std_msgs is already pulled in.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-opencv \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN if [ "${ROS_DISTRO}" = "jazzy" ]; then \
        pip3 install --no-cache-dir --break-system-packages -r requirements.txt; \
    else \
        pip3 install --no-cache-dir -r requirements.txt; \
    fi

COPY *.py ./
COPY adapters/ ./adapters/
COPY utils/ ./utils/
COPY game/ ./game/
COPY static/ ./static/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7999

ENTRYPOINT ["/entrypoint.sh"]
