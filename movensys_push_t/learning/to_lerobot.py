#!/usr/bin/env python3
# Converter for movensys_push_t recordings (schema of movensys-imitation, MIT).
"""Convert recorded episodes (datasets/<name>/raw/*.npz + movensys_episodes.jsonl) to LeRobot.

Run from movensys_push_t/ with the venv active (``source env.bash``):

    pusht-to-lerobot pusht_cr3a_sim          # -> datasets/lerobot/pusht_cr3a_sim, repo movensys/pusht_cr3a_sim

The features are movensys-imitation's recorder schema, so the policy configs and
``lerobot-dataset-viz`` work unchanged. Every converted episode gets a line in
<root>/meta/movensys_episodes.jsonl with its LeRobot ``episode_index``; episodes already converted
(same ``raw_index`` and ``source``) are skipped, so re-run it after each recording session.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

TASK = "Push the T-shaped block onto the T-shaped target."
SIDECAR = "movensys_episodes.jsonl"


def recorder_features(size: int) -> dict:
    return {
        "observation.images.top": {"dtype": "video", "shape": (size, size, 3),
                                   "names": ["height", "width", "channels"]},
        "observation.state": {"dtype": "float32", "shape": (2,), "names": ["x", "y"]},
        "action": {"dtype": "float32", "shape": (2,), "names": ["x", "y"]},
        "observation.joints": {"dtype": "float32", "shape": (6,),
                               "names": [f"joint{i}" for i in range(1, 7)]},
        "block_pose": {"dtype": "float32", "shape": (3,), "names": ["x", "y", "yaw"]},
        "coverage": {"dtype": "float32", "shape": (1,), "names": None},
        "iou": {"dtype": "float32", "shape": (1,), "names": None},
    }


def read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="dataset name under datasets/ (as recorded on the page)")
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent.parent / "datasets")
    ap.add_argument("--repo-id", default=None, help="default: movensys/<name>")
    ap.add_argument("--root", type=Path, default=None, help="default: <data-dir>/lerobot/<name>")
    ap.add_argument("--robot-type", default="dobot_cr3a")
    args = ap.parse_args()
    args.src = args.data_dir / args.name
    args.repo_id = args.repo_id or f"movensys/{args.name}"
    args.root = args.root or args.data_dir / "lerobot" / args.name

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    src = args.src.expanduser().resolve()
    episodes = read_lines(src / SIDECAR)
    if not episodes:
        raise SystemExit(f"no episodes in {src / SIDECAR}")
    root = args.root.expanduser()
    sidecar = root / "meta" / SIDECAR
    done = {(e.get("source"), e.get("raw_index")) for e in read_lines(sidecar)}
    todo = [e for e in episodes if (str(src), e["raw_index"]) not in done]
    if not todo:
        print("nothing new to convert")
        return

    fps = int(todo[0]["fps"])
    size = None
    dataset = None
    for e in todo:
        z = np.load(src / e["file"])
        images = z["observation__images__top"]
        if size is None:
            size = int(images.shape[1])
            if (root / "meta" / "info.json").exists():
                dataset = LeRobotDataset.resume(args.repo_id, root=root, image_writer_threads=4)
            else:
                dataset = LeRobotDataset.create(repo_id=args.repo_id, fps=fps, root=root,
                                                features=recorder_features(size),
                                                robot_type=args.robot_type, use_videos=True,
                                                image_writer_threads=4)
        index = int(dataset.meta.total_episodes)
        for k in range(images.shape[0]):
            dataset.add_frame({
                "observation.images.top": images[k],
                "observation.state": z["observation__state"][k],
                "action": z["action"][k],
                "observation.joints": z["observation__joints"][k],
                "block_pose": z["block_pose"][k],
                "coverage": z["coverage"][k],
                "iou": z["iou"][k],
                "task": e.get("task", TASK),
            })
        dataset.save_episode()
        line = {**e, "episode_index": index, "repo_id": args.repo_id, "source": str(src)}
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        with sidecar.open("a") as f:
            f.write(json.dumps(line) + "\n")
        print(f"raw {e['raw_index']} -> episode {index} ({images.shape[0]} frames, "
              f"{e.get('input_device', '')}, {e.get('stop_reason', '')})")
    dataset.finalize()


if __name__ == "__main__":
    main()
