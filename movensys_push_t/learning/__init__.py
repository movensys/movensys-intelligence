"""PushT policy learning for movensys_push_t (host venv, not the container).

Train, convert and run policies on the demonstrations recorded with the imitation page:

* ``policies/``        Flow Matching policy (``flow_matching_unet``) registered with LeRobot;
                       Diffusion Policy and ACT come with LeRobot itself.
* ``configs/``         policy configs and ``train_pusht.yaml`` (the task config).
* ``to_lerobot.py``    raw episodes (``datasets/<name>/raw``) -> LeRobot dataset.
* ``cli.py``           ``pusht-train`` / ``pusht-eval``: LeRobot's train / eval with the
                       project policies registered and comma-separated config files merged.
* ``inference.py``     ``PolicyRunner``: one checkpoint, one episode at a time.
* ``policy_runner.py`` ROS 2 node driving the planar guard from a checkpoint.
* ``offline_check.py`` open-loop check of a checkpoint on recorded episodes.

Policies, cli and inference come from movensys-imitation (origin/devel, 2026-11-22, MIT).
Setup: ``setup_venv.sh`` and ``doc/train.md``.
"""
