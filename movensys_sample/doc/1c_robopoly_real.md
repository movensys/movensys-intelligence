# Running Robopoly Game
## 1. Execution Procedure

### Step 1: Launch wmx-r2 (Terminal 1)
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/doc
./run_robopoly.sh wmx-r2
```




### Step 2a: Build containers on Nvidia env (Terminal 2)
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/doc
./run_robopoly.sh build_nvidia
```

### Step 2b-1: Build vllm containers on Intel env (Terminal 2)
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/doc
./run_robopoly.sh build_intel_vllm
```

### Step 2b-2: Build other containers (Terminal 3)
```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/doc
./run_robopoly.sh build_intel
```


### Step 3. Run moveit, containers, yolo (Terminal 3)
- Make sure whether the build process is done.
```bash
docker logs -f movensys_manipulator_container
```

- Run the demo
```bash
./run_robopoly.sh run
```






## 2. Debug tips (Optional)
### 2-1. vllm
```
docker logs -f vllm_container
```
### 2-2. movensys-manipulator
```
docker logs -f movensys-manipulator
```
### 2-3. moveit
```
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