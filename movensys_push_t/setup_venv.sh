#!/usr/bin/env bash
# Create movensys_push_t/.venv for policy learning (doc/train.md): uv venv on the system Python
# 3.12 with --system-site-packages so ROS 2 Jazzy's rclpy is importable next to LeRobot.
# Adapted from movensys-imitation scripts/setup_venv.sh (origin/devel, MIT).
set -eo pipefail   # no -u: /opt/ros/jazzy/setup.bash references unset variables
cd "$(dirname "${BASH_SOURCE[0]}")"

ROS_SETUP=/opt/ros/jazzy/setup.bash
[ -f "$ROS_SETUP" ] || { echo "ROS 2 Jazzy not found ($ROS_SETUP)" >&2; exit 1; }
command -v uv >/dev/null 2>&1 || { echo ">> installing uv"; curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }

if [ -f /etc/nv_tegra_release ] && [ "$(uname -m)" = "aarch64" ]; then
    TORCH_INDEX=https://download.pytorch.org/whl/cu130   # Jetson Thor (sm_110 needs CUDA 13)
else
    TORCH_INDEX=https://download.pytorch.org/whl/cu128   # RTX 5090 (sm_120 needs cu128)
fi

# shellcheck disable=SC1090
source "$ROS_SETUP"
[ -d .venv ] || uv venv --python /usr/bin/python3.12 --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo ">> torch ($TORCH_INDEX)"
uv pip install "torch>=2.7,<2.12" "torchvision>=0.22,<0.27" --index-url "$TORCH_INDEX"
echo ">> lerobot and the learning package"
uv pip install -e ".[viz]"

python - <<'PY'
import numpy, torch, lerobot, rclpy  # noqa: F401
from learning.policies import register_all
print("cuda:", torch.cuda.is_available(), "| torch", torch.__version__, "| lerobot", lerobot.__version__,
      "| numpy", numpy.__version__, "| policies", register_all(), "| rclpy OK")
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))
PY
echo ">> done: source env.bash"
