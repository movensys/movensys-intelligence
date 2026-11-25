#!/usr/bin/env bash
# Source in every terminal that trains or runs policies (doc/train.md, doc/inference.md):
#   source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash
# Keeps ROS_DOMAIN_ID / RMW from ~/.bashrc (the same as the containers and Isaac Sim).
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
if [ -f "$_HERE/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$_HERE/.venv/bin/activate"
else
    echo "no venv yet: run $_HERE/setup_venv.sh" >&2
fi
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"   # datasets and checkpoints are local
cd "$_HERE"
unset _HERE
