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
