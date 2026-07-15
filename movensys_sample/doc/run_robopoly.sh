#!/usr/bin/env bash
set -e

MODE=${1:-}
case "$MODE" in
  wmx-r2|build_nvidia|build_intel_vllm|build_intel|run) ;;
  *)
    echo "Usage: $0 {wmx-r2|build_nvidia|build_intel_vllm|build_intel|run}" >&2
    echo "  wmx-r2                       Launch the wmx-r2 manipulator driver (foreground, prompts for sudo)" >&2
    echo "  build_nvidia                   Rebuild docker images and start persistent containers (NVIDIA GPU)" >&2
    echo "  build_intel_vllm               Down all + drop caches + build/run vllm only (Intel GPU)" >&2
    echo "  build_intel                    Build remaining services: vectordb, vlm, whisper, manipulator, robopoly (Intel GPU)" >&2
    echo "  run                            Start runtime containers + ROS launches in a tmux session" >&2
    echo "" >&2
    echo "Recommended order (each in its own terminal):" >&2
    echo "  Terminal 1:  $0 wmx-r2" >&2
    echo "  Terminal 2:  $0 build_nvidia       (NVIDIA GPU, only when code/images change)" >&2
    echo "  Terminal 2:  $0 build_intel_vllm   (Intel GPU,  only when code/images change)" >&2
    echo "  Terminal 2:  $0 build_intel        (Intel GPU,  after build_intel_vllm)" >&2
    echo "  Terminal 3:  $0 run" >&2
    exit 1
    ;;
esac

# ============================================================================
# BUILD MODE: 3-phase sequence mirrors movensys_vlm/doc/running.md
#   Phase A — DOWN everything first
#       Step 1: down movensys_vlm + vectordb + whisper
#       Step 2: down vllm
#       (+ manipulator + robopoly — local additions outside running.md)
#   Phase B — DROP CACHES (Step 3)
#   Phase C — BUILD + UP sequentially
#       Step 4: vllm   (4a nvidia/Thor/B60, 4b Intel Panther Lake)
#       Step 5: vectordb + phoenix + movensys_vlm
#       Step 6: whisper (en, --force-recreate)
#       (+ manipulator + robopoly)
#
# Modes:
#   build_nvidia        Phase A + B + C (Step 4a vllm, then Steps 5-9)
#   build_intel_vllm    Phase A + B + C (Step 4b vllm only)
#   build_intel         Steps 5-9 only (run after build_intel_vllm)
# ============================================================================

# ----- Phase A: DOWN everything --------------------------------------------
_build_down() {
  echo "==> [Phase A] down all containers"

  echo "all of docker down"
  cd "${MOVENSYS_MANIPULATOR_PACKAGES}/docker"
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" \
                 -f "movensys_manipulator.${CPU_ARCH}.yaml" down

  cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
  COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
  COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml down
  COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
  COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml down

  cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
  docker compose down
}

# ----- Phase B: DROP CACHES ------------------------------------------------
_build_drop_caches() {
  echo "==> [Phase B] release memory caches"
  sync && sudo sysctl vm.drop_caches=3
}

# ----- Phase C, Steps 5-9: remaining services build + up -------------------
_build_services() {
  cd ~/workspaces/movensys-intelligence/movensys_vlm/docker

  echo "  -- Step 5: movensys_vlm build + up"
  export PHOENIX_TRACING=0
  COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build
  COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml up -d --force-recreate

  echo "  -- Step 6: whisper build + up (en, --force-recreate)"
  COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml build
  WHISPER_DEFAULT_LANGUAGE=en COMPOSE_PROFILES=$XPU_CORE \
    docker compose -f whisper.yaml up -d --force-recreate

  echo "  -- Step 7: movensys-manipulator build + up"
  cd "${MOVENSYS_MANIPULATOR_PACKAGES}/docker"
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" \
                 -f "movensys_manipulator.${CPU_ARCH}.yaml" build
  docker compose -f "${MOVENSYS_ROS_VERSION}.yaml" \
                 -f "movensys_manipulator.${CPU_ARCH}.yaml" up -d

  echo "  -- Step 8: robopoly build + up"
  export MOVENSYS_PNP_DRY_RUN=0
  cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
  docker compose build
  docker compose up -d
}

if [[ "$MODE" == "build_nvidia" ]]; then
  _build_down
  _build_drop_caches

  # ----- Phase C: BUILD + UP sequentially ----------------------------------
  echo "==> [Phase C] build + up sequentially"
  cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
  echo "  -- Step 4a: vllm build + up (Nvidia/Thor/B60)"
  COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml build
  COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml up -d

  _build_services

  echo "==> [build] done"
  exit 0
fi

if [[ "$MODE" == "build_intel_vllm" ]]; then
  _build_down
  _build_drop_caches

  # ----- Phase C: vllm only ------------------------------------------------
  echo "==> [Phase C] vllm build + up"
  cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
  echo "  -- Step 4b: vllm build + run (Intel Panther Lake)"
  ./vllm-intel-build.sh
  ./vllm-intel-run.sh
fi

if [[ "$MODE" == "build_intel" ]]; then
  # Steps 5-9 only — run after build_intel_vllm has brought vllm up.
  echo "==> [build_intel] build + up remaining services"
  _build_services

  echo "==> [build] done"
  exit 0
fi

# ============================================================================
# WMX R2 MODE: foreground manipulator driver, owns its own terminal + sudo
# ============================================================================
if [[ "$MODE" == "wmx-r2" ]]; then
  echo "==> [wmx-r2] launching manipulator driver"
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
                  && ros2 launch wmx_r2_package wmx_r2_cr3a_manipulator.launch.py use_sim_time:=false"
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

# --- Window 2: YOLO cube detection -------------------------------------------
tmux new-window -t "$SESSION" -n yolo
tmux send-keys -t "$SESSION:yolo" "\
mros ros2 launch movensys_manipulator_perception yolo_dice_and_cube_detector.launch.py \
" Enter
sleep 3

tmux select-window -t "$SESSION:moveit"
tmux attach -t "$SESSION"
