ARG ROS_DISTRO
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO

USER root

RUN rm -f /etc/apt/sources.list.d/yarn.list || true

RUN if [ "${ROS_DISTRO}" = "jazzy" ]; then \
      sed -i -E 's|http://(archive\|security)\.ubuntu\.com/ubuntu/|https://\1.ubuntu.com/ubuntu/|g' \
        /etc/apt/sources.list.d/ubuntu.sources; \
    elif [ "${ROS_DISTRO}" = "humble" ]; then \
      sed -i -E 's|http://(archive\|security)\.ubuntu\.com/ubuntu/|https://\1.ubuntu.com/ubuntu/|g' \
        /etc/apt/sources.list; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-colcon-common-extensions \
    python3-opencv \
    python3-numpy \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-moveit-ros-planning-interface \
    ros-${ROS_DISTRO}-tf2-ros \
    ros-${ROS_DISTRO}-tf2-geometry-msgs \
    ros-${ROS_DISTRO}-rclcpp-action \
    ros-${ROS_DISTRO}-control-msgs \
    ros-${ROS_DISTRO}-trajectory-msgs \
    && rm -rf /var/lib/apt/lists/*

# Web API only (no AI clients). Pin numpy<2 on jazzy: apt's python3-opencv is
# built against the numpy 1.x ABI.
RUN if [ "${ROS_DISTRO}" = "jazzy" ]; then \
        pip3 install --no-cache-dir --break-system-packages --ignore-installed "numpy<2" fastapi "uvicorn[standard]" pydantic; \
    elif [ "${ROS_DISTRO}" = "humble" ]; then \
        pip3 install --no-cache-dir fastapi "uvicorn[standard]" pydantic; \
    fi

WORKDIR /app

COPY *.py ./
COPY static/ ./static/
COPY config/ ./config/
COPY docker/movensys_push_t-entrypoint.sh /movensys_push_t-entrypoint.sh
RUN chmod +x /movensys_push_t-entrypoint.sh

# API port; override with PUSH_T_PORT (docker/.env).
EXPOSE 7000

ENTRYPOINT ["/movensys_push_t-entrypoint.sh"]
