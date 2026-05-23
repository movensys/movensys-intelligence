# Running Robopoly Game
## Execution Procedure

### Step 1: Open Isaac Sim (PC1)
`~/workspaces/movensys-simulation/dobot_cr3a/6c_robopoly_real.usd`

### Step 2: Run wmx-ros2 for manipulator (PC2, terminal 1)
check `~/workspaces/movensys_ws/src/wmx-ros2/doc/launch_<MANIPULATOR_MODEL>_manipulator.md`

For Taipei demo, please run
```bash
sudo --preserve-env=PATH \
     --preserve-env=AMENT_PREFIX_PATH \
     --preserve-env=COLCON_PREFIX_PATH \
     --preserve-env=PYTHONPATH \
     --preserve-env=LD_LIBRARY_PATH \
     --preserve-env=ROS_DISTRO \
     --preserve-env=ROS_VERSION \
     --preserve-env=ROS_PYTHON_VERSION \
     --preserve-env=ROS_DOMAIN_ID \
     --preserve-env=RMW_IMPLEMENTATION \
     bash -c "source /opt/ros/${ROS_DISTRO}/setup.bash && source $HOME/workspaces/movensys_ws/install/setup.bash && \
     ros2 launch wmx_ros2_package wmx_ros2_cr3a_manipulator.launch.py use_sim_time:=false"
```

### Step 3: Restart movensys_manipulator_container (PC2, terminal 2)
If user are restart PC, we recommend to restart and run `movensys_manipulator_container.
```bash
cd ${MOVENSYS_MANIPULATOR_PACKAGES}/docker                                                                              
docker compose -f ${MOVENSYS_ROS_VERSION}.yaml -f movensys_manipulator.${CPU_ARCH}.yaml down
docker compose -f ${MOVENSYS_ROS_VERSION}.yaml -f movensys_manipulator.${CPU_ARCH}.yaml build            
docker compose -f ${MOVENSYS_ROS_VERSION}.yaml -f movensys_manipulator.${CPU_ARCH}.yaml up -d 
```

Please check the log as follows:
```bash
docker logs -f movensys_manipulator_conatiner
```

### Step 4: Launch MoveIt2's OMPL + API (PC2, terminal 2)
```
mros ros2 launch movensys_manipulator_moveit_config moveit.launch.py use_sim_time:=true
```

If user cannot see the moveit GUI, let's check xhost setting for container.
```bash
xhost +local:docker
source ~/.bashrc
```

### Step 5: Run YOLO for cube detection (PC2, terminal 3)
```bash
mros ros2 launch movensys_manipulator_perception yolo_dice_and_cube_detector.launch.py
```

# Step 6: Stop and delete existed docker (PC2, terminal 4)
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml down
```

## Step 7: Release memory stuck for Jetson Thor and Intel Panther lake (PC2, terminal 4)
```
sync && sudo sysctl vm.drop_caches=3
```

## Step 8: Build and run vllm (PC2, terminal 4)
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
./vllm-intel-build.sh
./vllm-intel-run.sh
```

## Step 9: Run vectorDB (PC2, terminal 5)
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml build
COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml up -d
```

## Step 10: Run movensys_vlm with phoenix (PC2, terminal 5)
```bash
docker run -d --rm --name phoenix \
    -p 6006:6006 -p 4317:4317 \
    arizephoenix/phoenix:latest
```

```bash
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
export PHOENIX_TRACING=1
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml down
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml build
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml up -d
```

## Running whispher english mode (PC2, terminal 5)
```bash
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml down
WHISPER_DEFAULT_LANGUAGE=en COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml up -d --force-recreate
```

#### Running movensys_robopoly (PC2, terminal 6)
```bash
export MOVENSYS_PNP_DRY_RUN=0
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build
docker compose up -d
```
