# Running a trained PushT policy (inference)

For a checkpoint trained with `train.md`, e.g.
`movensys_push_t/outputs/diffusion_s1/checkpoints/last/pretrained_model`.

The policy runs in `pusht-policy-runner` (`learning/policy_runner.py`, host venv, GPU). It reads
the same grayscale ROI image the recorder stored and sends targets to the push_t planar guard,
so every safety limit of teleop also applies to the policy:

```
/pusht/policy_image (256 x 256 gray) --+
/wmx/moveit2/eef_pose (tip x, y) ------+--> pusht-policy-runner --> /pusht/target_raw --> planar guard --> MoveIt Servo
/episode_recorder/state (gate) --------+          (10 Hz)                             (area clamp, 5 mm step, 30 mm lead,
                                                                                         fixed height and orientation)
```

The runner only acts while the page records an episode (`/episode_recorder/state` is
`recording:<n>`), so episodes are started and stopped on the page, and every policy episode is
saved like a demonstration: the dataset is the record of how the policy did.

`keyboard_teleop` uses its own topic (`/pusht/teleop_target`); the guard follows the policy only
during a policy episode and keyboard_teleop the rest of the time, so it can stay open.

## 1. Bring-up

1. 9a step 1 to 3 running (Isaac Sim, `sim_bridge`, `imitation_push_t.launch.py`), push_t
   container up, `localhost:7000/imitation.html` open, guard enabled (it enables itself).
2. The ROI in step 2 must be the one the training data was recorded with (saved with the dataset
   in `datasets/<name>/calibration/calibration.yaml`). Do not press Auto ROI again unless you
   retrain.

## 2. Start the policy runner

```bash
source ~/workspaces/movensys-intelligence/movensys_push_t/env.bash
pusht-policy-runner --ros-args -p use_sim_time:=true -p run_mode:=slow \
    -p pretrained:=outputs/diffusion_s1/checkpoints/last/pretrained_model \
    -p policy_overrides:="--policy.noise_scheduler_type=DDIM --policy.num_inference_steps=10"
```

* Flow Matching: `-p policy_overrides:="--policy.fm_num_steps=4"`.
* The push area (for clamping and the sheet frame) is read from `config/imitation.yaml`, the
  same file the page uses.
* Wait for `policy diffusion on cuda, mode slow` in the log (a second of CUDA warm-up), then
  `ros2 topic echo /policy_runner/state` shows `idle` until an episode records, then `running:<n>`.
* Real robot: `-p use_sim_time:=false`.

## 3. Run episodes from the page

Step 3: dataset e.g. `eval_diffusion_s1` (keep evaluation runs out of the training dataset),
input **policy**, episodes e.g. 10, length 30 s, **start from home** on. Per episode put the T
somewhere new in Isaac Sim (with **wait for Record** on, press **Record** when ready); the policy
then pushes for the full 30 s (Stop is ignored; **Discard** or **Abort** end it early).

## 4. Modes: shadow, slow, normal

Go through them in this order for every new checkpoint (restart the runner with another
`-p run_mode:=`):

| Mode | What moves the arm | Use |
|---|---|---|
| `shadow` | you, with `keyboard_teleop`; the runner only publishes its prediction on `/pusht/policy_target` | check the predictions without letting the policy move: run a **teleop** session and compare `/pusht/policy_target` with where you push |
| `slow` | the policy, each target at most 10 mm from the tip (0.1 m/s) | first closed-loop runs |
| `normal` | the policy, at the guard's limits | evaluation once `slow` looks right |

## 5. Judging the model

There is no automatic score. Review the episodes in step 4 (frame scrubber and tip / action plot)
and count, over a fixed set of start poses, how often the T ends on the goal within 30 s. Keep a
model when it does so from most start poses in `normal` mode. Typical failures:

* Pushes but never finishes: more demonstrations, especially of the final alignment.
* Pushes the T off the goal or oscillates near it: train longer, or try Flow Matching.
* Drives to one place and stays: the input does not match training (ROI changed); run the
  offline check in `train.md`.

## Troubleshooting

* Runner stays `idle` during an episode: the session input is not **policy**, or the runner does
  not see the page's topics: `echo $ROS_DOMAIN_ID` must be 13 and `ros2 topic list | grep pusht`
  must list `/pusht/policy_image`.
* Runner state `stale`: no fresh image or tip pose (older than 0.3 s / 0.5 s); check the camera
  age on the page.
* The arm does not follow in `slow`/`normal`: the tool is lifted (start from home lowers it, or
  press **Lower**), or the guard is disabled (step 1).
