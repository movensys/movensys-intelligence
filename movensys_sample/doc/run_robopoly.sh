#!/usr/bin/env bash
set -e

MODE=${1:-}
case "$MODE" in
  wmx-ros2|build_nvidia|build_intel|run) ;;
  *)
    echo "Usage: $0 {wmx-ros2|build|run}" >&2
    echo "  wmx-ros2                       Launch the wmx-ros2 manipulator driver (foreground, prompts for sudo)" >&2
    echo "  build_nvidia / build_intel     Rebuild docker images and start persistent containers" >&2
    echo "  run                            Start runtime containers + ROS launches in a tmux session" >&2
    echo "" >&2
    echo "Recommended order (each in its own terminal):" >&2
    echo "  Terminal 1:  $0 wmx-ros2" >&2
    echo "  Terminal 2:  $0 build   (only when code/images change)" >&2
    echo "  Terminal 2:  $0 run" >&2
    exit 1
    ;;
esac

# ============================================================================
# WMX-ROS2 MODE: foreground manipulator driver, owns its own terminal + sudo
# ============================================================================
if [[ "$MODE" == "wmx-ros2" ]]; then
  echo "==> [wmx-ros2] launching manipulator driver"
  exec sudo --preserve-env=PATH \
            --preserve-env=AMENT_PREFIX_PATH \
            --preserve-env=COLCON_PREFIX_PATH \
            --preserve-env=PYTHONPATH \
            --preserve-env=LD_LIBRARY_PATH \
            --preserve-env=ROS_DISTRO \
            --preserve-env=ROS_VERSION \
            --preserve-env=ROS_PYTHON_VERSION \
            --preserve-env=ROS_DOMAIN_ID \
            --preserve-env=RMW_IMPLEMENTATION \
            bash -c "source /opt/ros/${ROS_DISTRO}/setup.bash \
                  && source ${HOME}/workspaces/movensys_ws/install/setup.bash \
                  && ros2 launch wmx_ros2_package wmx_ros2_cr3a_manipulator.launch.py use_sim_time:=false"
fi

# ============================================================================
# BUILD MODE: rebuild docker images; also bring up the persistent containers
# ============================================================================
if [[ "$MODE" == "build_nvidia" ]]; then
  echo "==> [build & run] manipulator container"
  cd "${MOVENSYS_MANIPULATOR_PACKAGES}/docker"
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" -f "movensys_manipulator.${CPU_ARCH}.yaml" down
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" -f "movensys_manipulator.${CPU_ARCH}.yaml" build
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" -f "movensys_manipulator.${CPU_ARCH}.yaml" up -d

  echo "==> [build & run] vllm"
  cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
  sync && sudo sysctl vm.drop_caches=3
  COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml down
  COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml build
  COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml up -d

  echo "==> [build] vectordb"
  COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml down
  COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml build

  echo "==> [build] phoenix + movensys_vlm"
  docker rm -f phoenix 2>/dev/null || true
  docker run -d --rm --name phoenix -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest
  COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
  COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build

  echo "==> [build] whisper"
  COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
  COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml build

  echo "==> [build] robopoly"
  cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
  docker compose down
  docker compose build

  echo "==> [build] done"
  exit 0
fi

if [[ "$MODE" == "build_intel" ]]; then
  echo "==> [build & run] manipulator container"
  cd "${MOVENSYS_MANIPULATOR_PACKAGES}/docker"
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" -f "movensys_manipulator.${CPU_ARCH}.yaml" down
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" -f "movensys_manipulator.${CPU_ARCH}.yaml" build
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" -f "movensys_manipulator.${CPU_ARCH}.yaml" up -d

  echo "==> [build & run] vllm"
  cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
  sync && sudo sysctl vm.drop_caches=3
  ./vllm-intel-build.sh
  ./vllm-intel-run.sh

  echo "==> [build] vectordb"
  COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml down
  COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml build

  echo "==> [build] phoenix + movensys_vlm"
  docker rm -f phoenix 2>/dev/null || true
  docker run -d --rm --name phoenix -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest
  COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
  COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build

  echo "==> [build] whisper"
  COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
  COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml build

  echo "==> [build] robopoly"
  cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
  docker compose down
  docker compose build

  echo "==> [build] done"
  exit 0
fi

# ============================================================================
# RUN MODE: bring runtime containers up + launch ROS nodes in a tmux session.
# ============================================================================
SESSION=robopoly

# Wipe any prior session so re-runs start clean
tmux kill-session -t "$SESSION" 2>/dev/null || true

# --- Window 1: MoveIt2 -------------------------------------------------------
tmux new-session -d -s "$SESSION" -n moveit
tmux send-keys -t "$SESSION:moveit" "\
mros ros2 launch movensys_manipulator_moveit_config moveit.launch.py use_sim_time:=true\
" Enter
sleep 3

# --- Window 2: VLM / vectordb / whisper / robopoly stacks ------------
tmux new-window -t "$SESSION" -n containers
tmux send-keys -t "$SESSION:containers" "\
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker \
&& COMPOSE_PROFILES=\$XPU_CORE docker compose -f vllm.yaml     up -d \
&& COMPOSE_PROFILES=\$CPU_ARCH docker compose -f vectordb.yaml up -d \
&& PHOENIX_TRACING=1 COMPOSE_PROFILES=\$XPU_CORE docker compose -f movensys_vlm.yaml up -d \
&& cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker \
&& MOVENSYS_PNP_DRY_RUN=0 docker compose up -d
" Enter
sleep 3

tmux send-keys -t "$SESSION:containers" "\
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker \
&& WHISPER_DEFAULT_LANGUAGE=en COMPOSE_PROFILES=\$XPU_CORE docker compose -f whisper.yaml up -d\
" Enter
sleep 3

# --- Window 3: YOLO cube detection -------------------------------------------
tmux new-window -t "$SESSION" -n yolo
tmux send-keys -t "$SESSION:yolo" "\
mros ros2 launch movensys_manipulator_perception yolo_dice_and_cube_detector.launch.py \
" Enter
sleep 3

tmux select-window -t "$SESSION:moveit"
tmux attach -t "$SESSION"
