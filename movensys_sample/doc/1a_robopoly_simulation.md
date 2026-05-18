# Running Robopoly Game
## Execution Procedure

### Step 1: Movensys-manipulator
check `movensys-manipulator/doc` 1_ and 2_
Run `movensys-manipulator/doc/6a_yolo_simulation.md`

### Step 2: Run VLM package
Run `movensys_vlm/doc/running.md`

### Step 3: Install movensys_robopoly
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Running movensys_robopoly
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly
export MOVENSYS_PNP_DRY_RUN=1
python3 -m uvicorn main:app --host 0.0.0.0 --port 7999
```

```bash
export MOVENSYS_PNP_DRY_RUN=1
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build
docker compose up
```

1. .venv
pip inst requirements 

python 경로 conflict vs (source ~/opt/usr/jazzy) PYTHONPATH



2. docker


### Step 5: Enjoy the robopoly game
1. Click `Toggle is_YOLO` and check `is_YOLO` is set to ON.
2. Click Reset game and play the game.