# Training a PushT policy

From demonstrations recorded on `localhost:7000/imitation.html` to a checkpoint. Running the
checkpoint on the arm is in `inference.md`.

Everything is in this folder (`movensys_push_t`): the policies (Diffusion Policy, Flow Matching,
ACT), the converter, training and the policy runner are the `learning/` package, installed in
`movensys_push_t/.venv` on the host. Nothing is trained inside the push_t container.

```
record (page)            convert                    train                         checkpoint
datasets/<name>/raw  ->  pusht-to-lerobot  ->  datasets/lerobot/<name>  ->  pusht-train  ->  outputs/<run>/checkpoints/last/pretrained_model
```

## 1. One-time setup

```bash
cd ~/workspaces/movensys-intelligence/movensys_push_t
./setup_venv.sh        # .venv on Python 3.12 (+ ROS 2 Jazzy rclpy), torch cu128, LeRobot 0.6.1; several GB
```

Then in every terminal that trains or runs a policy:

```bash
source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash   # venv, ROS, cd movensys_push_t
```

`env.bash` keeps `ROS_DOMAIN_ID` and `RMW_IMPLEMENTATION` from `~/.bashrc` (13, cyclonedds), the
same as the containers and Isaac Sim.

## 2. Record demonstrations

On the page, with 9a step 1 to 3 running and `keyboard_teleop` remapped (`running.md`):

1. Step 2: **Auto ROI** once, then leave the ROI alone for the whole dataset. The policy learns
   this exact grayscale 256 x 256 view; a different ROI means a new dataset.
2. Step 3: dataset `pusht_cr3a_sim` (or your own name), operator, input **teleop**,
   **start from home** and **wait for Record** on, episode length 30 s.
3. Per episode: move the T in Isaac Sim to a new start pose, press **Record**, push the T onto the
   black goal T with `keyboard_teleop`, press **Stop & save**. Press `p` in `keyboard_teleop` when
   the page asks (after the arm went home).
4. Step 4: review episodes; **Delete last episode** for a bad one.

How many: a 65-episode pilot (movensys-imitation, same setup) gave policies that pushed the T
toward the goal but did not finish reliably; plan for 150 to 200. Vary the T start pose
(position and rotation) over the whole sheet and keep the pushing style consistent.

## 3. Convert to a LeRobot dataset

```bash
source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash
pusht-to-lerobot pusht_cr3a_sim        # -> datasets/lerobot/pusht_cr3a_sim (repo id movensys/pusht_cr3a_sim)
```

Re-run it after every recording session: converted episodes are skipped, new ones appended.
Look at the result:

```bash
lerobot-dataset-viz --repo-id movensys/pusht_cr3a_sim --root datasets/lerobot/pusht_cr3a_sim --episode-index 0
```

## 4. Train

`learning/configs/train_pusht.yaml` is the task config (20 000 steps, batch 64, the 256 x 256
frame resized to 96 x 96 with an 84 x 84 crop, a checkpoint every 5 000 steps, no gym
evaluation). It goes **last**, after a policy config:

```bash
source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash

# Diffusion Policy
pusht-train --config_path=learning/configs/diffusion.yaml,learning/configs/train_pusht.yaml \
    --seed=1 --output_dir=outputs/diffusion_s1

# Flow Matching (same network, flow-matching objective)
pusht-train --config_path=learning/configs/flow_matching.yaml,learning/configs/train_pusht.yaml \
    --seed=1 --output_dir=outputs/flow_matching_s1
```

* Another dataset: add `--dataset.repo_id=movensys/<name> --dataset.root=datasets/lerobot/<name>`.
* A new `--output_dir` per run (LeRobot refuses to overwrite one).
* Time on the RTX 5090: about 15 steps/s, so 20 000 steps take about 25 minutes (slower while
  Isaac Sim runs). Out of GPU memory with Isaac open: `--batch_size=32`.
* The checkpoint: `outputs/<run>/checkpoints/last/pretrained_model` (intermediate ones in
  `005000`, `010000`, ...).

ACT (`learning/configs/act.yaml`) trains the same way but scored lowest on PushT in the
movensys-imitation benchmark; start with Diffusion or Flow Matching.

## 5. Offline check (before the arm moves)

Runs recorded episodes through the checkpoint and compares the predicted target with what the
operator did. Keep a few episodes out of training for it: train with
`--dataset.episodes="[0,1,...]"` listing all but the last five, then:

```bash
source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash
pusht-offline-check outputs/diffusion_s1/checkpoints/last/pretrained_model pusht_cr3a_sim \
    --policy.noise_scheduler_type=DDIM --policy.num_inference_steps=10 --out outputs/diffusion_s1/offline.csv
```

It checks the last five recorded episodes unless `--episodes 40 41 ...` is given (raw indices as
on the page). Flow Matching: `--policy.fm_num_steps=4` instead of the two DDIM options.

Reading it: `policy_mm` must beat `hold_mm` (predicting the current tip position) for the policy
to have learnt anything; a large `bias_mm`, or errors near the size of the sheet, mean a
preprocessing bug rather than too little data. `direction_agreement` (prediction points the way
the operator moved) should be well above chance (0.25).

## What counts as a good model

The page does not score episodes, so judge on the arm (`inference.md`): `shadow`, then `slow`,
and call it good when it pushes the T onto the goal from most start poses within the 30 s
episode in `normal` mode.

## Troubleshooting

* `pusht-train: command not found`: `source env.bash`; if it says "no venv yet", run `./setup_venv.sh`.
* `--policy.type=flow_matching_unet` unknown: run with `pusht-train` (it registers the policy), not `lerobot-train`.
* A long `Could not load libtorchcodec ... libavutil.so.60` warning at start-up is harmless:
  torchcodec does not match the system FFmpeg 6 and LeRobot decodes the videos with PyAV instead.
* A recorded dataset name cannot be `calibration` or `lerobot` (reserved folders under `datasets/`).
