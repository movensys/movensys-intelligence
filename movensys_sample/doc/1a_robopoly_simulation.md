# Running Robopoly Game 
## Step 1: Movensys-manipulator
Follow 1_setup.md in `movensys-manipulator/doc` and set to `export MOVENSYS_ROS_VERSION=general` in ~/.bashrc configuration
Follow 2_docker.md in `movensys-manipulator/doc`.


## Step 2: Open Isaac Sim
`~/workspaces/movensys-simulation/<MANIPULATOR_MODEL>/7a_robopoly_simulation.usd`

## Step 3: Run simulator bridge
```
mros ros2 launch movensys_manipulator_moveit_config sim_bridge.launch.py simulator:=isaacsim use_sim_time:=true 
```

## Step 4a: Launch MoveIt2's OMPL + API
```
mros ros2 launch movensys_manipulator_moveit_config moveit.launch.py use_sim_time:=true
```

## Step 4b: Launch cuMotion + API
```
mros ros2 launch movensys_manipulator_isaac_ros_config isaac_cumotion.launch.py use_sim_time:=true
```

## Step 5: Launch Yolo detector
```
mros ros2 launch movensys_manipulator_perception yolo_dice_and_cube_detector.launch.py use_sim_time:=true
```

## Step 6: Run VLM package
Run `movensys_vlm/doc/running.md`

## Step 7: Running movensys_robopoly
```
export MOVENSYS_PNP_DRY_RUN=0
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build
docker compose up -d
```

## Step 8: Enjoy the robopoly game
1. Click `Toggle is_YOLO` and check `is_YOLO` is set to ON.
2. Click Reset game and play the game.


# Running Robopoly Game w/o moving robot arm
## Step 1: Running movensys_robopoly in DRY RUN mode
```
export MOVENSYS_PNP_DRY_RUN=1
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build
docker compose up -d
```

## Step 2: Enjoy the robopoly game
1. Click `Toggle is_YOLO` and check `is_YOLO` is set to OFF.
2. Set your microphone.
3. Click Reset game.
4. Press `Z` key and speak into microphone to request one of game action.
5. Press `X` key and speak to communicate game status, game strategies, etc.

# Step 3: Auto dry run test (optional)
```
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/
python3 scripts/auto_play_dry_run.py
```