# Running Robopoly Game
## Execution Procedure

### Step 1. Launch wmx-ros2 (Terminal 1)
```bash
cd ~/workspaces/movensys-intelligence/doc
./run_robopoly.sh wmx-ros2
```

### Step 2. Build containers (Terminal 2)
1. Build & Run movensys-manipulator, vllm
2. Build whispher, vectorDB, movensys-robopoly, movensys_vlm
```bash
./run_robopoly.sh build
```

After sucess of running `vllm_container` and `movensys-manipulator`,
move Step 3.

### Step 3. Run moveit, containers, yolo (Terminal 3)
```bash
./run_robopoly.sh run
```


## Debug tips (Optional)
### vllm
```bash
docker logs -f vllm_container
```
### movensys-manipulator
```bash
docker logs -f movensys-manipulator
```
### moveit
```bash
tmux a -t robopoly
```

### tmux
1. excape tmux
- Sequentially press `Ctrl b` and `d`

2. move screen
- Sequentially press `Ctrl b` and `<screen_number>`

3. Visual mode
- Sequentially press `Ctrl b` and `[`
- Then, use `PgUp` or `PgDn`. 