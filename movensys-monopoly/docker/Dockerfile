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
# Camera/imaging deps land in M4 when ros2_node.py starts subscribing
# to /image_* topics.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
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

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
