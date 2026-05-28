# Running Robopoly Game
## 1. Execution Procedure

### Step 1: Launch wmx-ros2 (Terminal 1)
```
cd ~/workspaces/movensys-intelligence/movensys_sample/doc
./run_robopoly.sh wmx-ros2
```




### Step 2a: Build containers on Nvidia env (Terminal 2)
```
./run_robopoly.sh build_nvidia
```

### Step 2b: Build containers on Intel env (Terminal 2)
```
./run_robopoly.sh build_intel
```





### Step 3. Run moveit, containers, yolo (Terminal 3)
```
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