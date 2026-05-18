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

# arize-phoenix + openinference-instrumentation-openai are runtime deps
# only when PHOENIX_TRACING is set.
RUN if [ "${ROS_DISTRO}" = "jazzy" ]; then \
        pip3 install --no-cache-dir --break-system-packages fastapi "uvicorn[standard]" pydantic "openai>=1.30.0" Pillow "python-multipart>=0.0.9" arize-phoenix openinference-instrumentation-openai; \
    elif [ "${ROS_DISTRO}" = "humble" ]; then \
        pip3 install --no-cache-dir fastapi "uvicorn[standard]" pydantic "openai>=1.30.0" Pillow "python-multipart>=0.0.9" arize-phoenix openinference-instrumentation-openai; \
    fi

WORKDIR /app

COPY *.py ./
COPY static/ ./static/
COPY docker/movensys_vlm-entrypoint.sh /movensys_vlm-entrypoint.sh
RUN chmod +x /movensys_vlm-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/movensys_vlm-entrypoint.sh"]
