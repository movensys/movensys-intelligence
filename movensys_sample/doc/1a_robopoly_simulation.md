# Running Robopoly Game
## Execution Procedure

### Step 1: Movensys-manipulator
check `movensys-manipulator/doc` 1_ and 2_
Run `movensys-manipulator/doc/6a_yolo_simulation.md`

### Step 2: Run VLM package
Run `movensys_vlm/doc/running.md`

### Step 3: Install uvicorn
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly
pip3 install --break-system-packages -r requirements.txt
```

### Step 4: Running movensys_robopoly
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly
python3 -m uvicorn main:app --host 0.0.0.0 --port 7999
```

### Step 5: Enjoy the robopoly game
1. Click `Toggle is_YOLO` and check `is_YOLO` is set to ON.
2. Click Reset game and play the game.