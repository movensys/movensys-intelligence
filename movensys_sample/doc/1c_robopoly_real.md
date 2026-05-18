# Running Robopoly Game
## Execution Procedure

### Step 1: Open Isaac Sim
`~/workspaces/movensys-simulation/dobot_cr3a/6a_robopoly_real.usd`

### Step 2: Run wmx-ros2 for manipulator
check `~/workspaces/movensys_ws/src/wmx-ros2/doc/launch_<MANIPULATOR_MODEL>_manipulator.md`

### Step 3: Launch MoveIt2's OMPL + API
```
mros ros2 launch movensys_manipulator_moveit_config moveit.launch.py use_sim_time:=true
```

### Step 4: Run YOLO for cube detection
```bash
cd ~/workspaces/movensys_ws/src/movensys-manpulator/movensys_manipulator_perception
mros ros2 launch movensys_manipulator_perception yolo_cube_detector.launch.py
```

### Step 5: Run YOLO for dice detection
```bash
cd ~/workspaces/movensys_ws/src/movensys-manpulator/movensys_manipulator_perception
mros ros2 launch movensys_manipulator_perception yolo_dice_detector.launch.py
```

### Step 6: Run YOLO debugger (Optional)
```bash
ros2 run rqt_image_view rqt_image_view /yolo_dice_detector/debug_image
ros2 run rqt_image_view rqt_image_view /yolo_cube_detector/debug_image
```

### Step 7: Running movensys_vlm
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml up -d
```

### Step 8: Running movensys_robopoly
#### Only first run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

#### Running movensys_robopoly
```bash
export MOVENSYS_PNP_DRY_RUN=1   # optional — skips real robot motion
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build            # only needed when deps/Dockerfile change
docker compose up               # foreground; Ctrl-C to stop
```

### Step 9: Play the robopoly game
1. Click `Toggle is_YOLO` and check `is_YOLO` is set to ON.
2. Click `Reset game` and `Roll dice`. Enjoy the game.