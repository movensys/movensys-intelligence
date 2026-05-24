# Running Robopoly Game
## 1. Execution Procedure

### Step 1. Launch wmx-ros2 (Terminal 1)
```bash
cd ~/workspaces/movensys-intelligence/doc
./run_robopoly.sh wmx-ros2
```

### Step 2. Build containers on Nvidia env (Terminal 2)
```bash
./run_robopoly.sh build_nvidia
```

### Step 2-2. Build containers on Intel env (Terminal 2)
```bash
./run_robopoly.sh build_intel
```

Check logs using 2-1, 2-2 commands.

### Step 3. Run moveit, containers, yolo (Terminal 3)
```bash
./run_robopoly.sh run
```
Check tmux logs using a 2-3, 2-4 command.


## 2. Debug tips (Optional)
### 2-1. vllm
```bash
docker logs -f vllm_container
```
### 2-2. movensys-manipulator
```bash
docker logs -f movensys-manipulator
```
### 2-3. moveit
```bash
tmux a -t robopoly
```

### 2-4. tmux
1. excape tmux
- Sequentially press `Ctrl b` and `d`

2. move screen
- Sequentially press `Ctrl b` and `<screen_number>`

3. Visual mode
- Sequentially press `Ctrl b` and `[`
- Then, use `PgUp` or `PgDn`. 