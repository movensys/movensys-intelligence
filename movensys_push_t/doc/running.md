# Running Movensys-Manipulator
check `doc/` number 9

# Bashrc Setup
```
export MANIPULATOR_MODEL=dobot_cr3a_custom_tool
export XPU_CORE=nvidia-gpu              #support{nvidia-gpu, intel-xpu} 
```
```
source ~/.bashrc
```



# Step 1: Stop and delete existed docker
```
cd ~/workspaces/movensys-intelligence/movensys_push_t/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_push_t.yaml down
sync && sudo sysctl vm.drop_caches=3
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_push_t.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_push_t.yaml up -d
```





# Running
open `localhost:7000` for robot controller and the top camera (camera_top_link: `/image_top/rgb`)
open `localhost:7000/docs` for checking APIs



# Imitation learning (PushT demonstrations)
Open `localhost:7000/imitation.html` (or the **Imitation learning** button on the control page).
Needs 9a step 1 to 3 running (Isaac Sim, `sim_bridge`, `imitation_push_t.launch.py`); do not run
`keyboard_teleop` at the same time (the planar guard is the only writer to MoveIt Servo).

The page walks through the whole process:
1. **Arm and planar guard**: Park (MoveIt) if needed, Enable guard (tool vertical, push height
   table + 10 mm, tip clamped to the 0.60 x 0.30 m push area), Lower / Lift.
2. **Camera ROI and T colour**: Auto ROI (from the camera TF) or Draw ROI on the image; Pick T
   colour by clicking the T. The recorded / policy image is the ROI at 256 x 256, black and white
   (T white on black) by default, gray or colour selectable.
3. **Record episodes**: teleop (W A S D / arrows, gamepad, or hold the mouse on the image) until
   Stop & save or the episode length; policy episodes always run the full length (default 30 s).
4. **Review datasets**: episode list, frame scrubber, tip / action plot, delete last.
5. **Train and run a policy**: copy-paste commands for the movensys-imitation venv
   (`scripts/to_lerobot.py` converts `datasets/<name>/raw/*.npz` to LeRobot; the
   `policy_runner` reads `/pusht/feedback_image`, the same image that was recorded).

Data: `movensys_push_t/datasets/<dataset>/` (raw episodes + `movensys_episodes.jsonl`) and
`datasets/calibration/<mode>/calibration.yaml` (ROI, T colour). Settings: `config/imitation.yaml`.
Real robot: `PUSHT_MODE=real PUSHT_USE_SIM_TIME=false` in `docker/.env`, and
`guard.latch_mode: measured` (park the tool at push height first).
