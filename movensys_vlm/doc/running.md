# Running Movensys-Manipulator
check `doc/` number 1,2,3 and 6

# ~/.bashrc setup
```
export VLM_CORE=nvidia-gpu              #support{nvidia-gpu, intel-xpu} 
```
```
source ~/.bashrc
```

# Setup Vllm
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$VLM_CORE docker compose -f vllm-compose.yaml down
COMPOSE_PROFILES=$VLM_CORE docker compose -f vllm-compose.yaml build
COMPOSE_PROFILES=$VLM_CORE docker compose -f vllm-compose.yaml up -d  
```

# Setup movensys_vlm
```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$VLM_CORE docker compose -f movensys_vlm.yaml down                                                                     
COMPOSE_PROFILES=$VLM_CORE docker compose -f movensys_vlm.yaml build
COMPOSE_PROFILES=$VLM_CORE docker compose -f movensys_vlm.yaml up -d
```

# Running
open `localhost:8000`

# Check API
open `localhost:8000/docs`