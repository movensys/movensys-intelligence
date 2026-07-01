# Running Robopoly Game 
## Step 1: Movensys-manipulator
check `movensys-manipulator/doc` 1_ and 2_
Run `movensys-manipulator/doc/6a_yolo_simulation.md` step 1-4

## Step 2: Run VLM package
Run `movensys_vlm/doc/running.md`

## Step 3: Running movensys_robopoly
```
export MOVENSYS_PNP_DRY_RUN=0
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build
docker compose up -d
```

## Step 4: Enjoy the robopoly game
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