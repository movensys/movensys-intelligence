"""Open-loop check of a checkpoint on recorded episodes, before the arm moves.

Adapted from movensys-imitation ``scripts/offline_check.py`` (origin/devel, MIT) to read
movensys_push_t's raw episodes directly. Each frame (image + tip position) goes through
:class:`learning.inference.PolicyRunner` in order and the predicted target is compared with the
recorded action. Two baselines on the same frames: ``hold`` (predict the current tip) and
``repeat`` (predict the previous action). The policy has learnt something once its error beats
``hold``; the direction agreement (prediction points the way the operator moved, within 45 deg,
on frames that moved more than 5 mm; chance 0.25) is the more telling number because pushes are
multimodal.

    source env.bash
    pusht-offline-check outputs/diffusion_s1/checkpoints/last/pretrained_model pusht_cr3a_sim \\
        --episodes 40 41 42 43 44 --policy.noise_scheduler_type=DDIM --policy.num_inference_steps=10
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent   # movensys_push_t/


def direction_agreement(state, target, pred, min_mm: float = 5.0, max_deg: float = 45.0) -> float:
    d_rec, d_pred = target - state, pred - state
    keep = np.linalg.norm(d_rec, axis=1) > min_mm / 1000
    if not keep.any():
        return float("nan")
    a, b = d_rec[keep], d_pred[keep]
    cos = (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-12)
    return float(np.mean(cos >= np.cos(np.radians(max_deg))))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pretrained", type=Path)
    ap.add_argument("dataset", help="dataset name under datasets/")
    ap.add_argument("--episodes", type=int, nargs="+", default=None,
                    help="raw episode indices (default: the last five)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--out", type=Path, default=None, help="per-frame CSV (a JSON summary goes next to it)")
    args, overrides = ap.parse_known_args()

    from learning.inference import PolicyRunner

    src = ROOT / "datasets" / args.dataset
    lines = [json.loads(x) for x in (src / "movensys_episodes.jsonl").read_text().splitlines() if x.strip()]
    by_index = {e["raw_index"]: e for e in lines}
    episodes = args.episodes or sorted(by_index)[-5:]
    pretrained = args.pretrained if args.pretrained.is_absolute() else ROOT / args.pretrained
    runner = PolicyRunner(pretrained, tuple(overrides), args.device)

    rows, all_state, all_act, all_pred, all_rep, lat = [], [], [], [], [], []
    for ep in episodes:
        z = np.load(src / by_index[ep]["file"])
        images, state, action = z["observation__images__top"], z["observation__state"], z["action"]
        runner.reset()
        prev = state[0]
        for k in range(len(action)):
            pred = runner.act(images[k], state[k])
            lat.append(runner.last_latency_ms)
            rows.append({"episode": ep, "frame": k, "state_x": state[k][0], "state_y": state[k][1],
                         "action_x": action[k][0], "action_y": action[k][1],
                         "pred_x": pred[0], "pred_y": pred[1]})
            all_state.append(state[k]); all_act.append(action[k]); all_pred.append(pred); all_rep.append(prev)
            prev = action[k]
    s, a, p, r = (np.asarray(v, float) for v in (all_state, all_act, all_pred, all_rep))
    err = lambda x: float(np.linalg.norm(x - a, axis=1).mean() * 1000)  # noqa: E731
    summary = {
        "checkpoint": str(pretrained), "episodes": episodes, "frames": len(a),
        "policy_mm": round(err(p), 1), "hold_mm": round(err(s), 1), "repeat_mm": round(err(r), 1),
        "bias_mm": [round(float(v) * 1000, 1) for v in (p - a).mean(0)],
        "direction_agreement": round(direction_agreement(s, a, p), 3),
        "direction_agreement_repeat": round(direction_agreement(s, a, r), 3),
        "latency_ms_median": round(float(np.median(lat[3:] or lat)), 1),
        "latency_ms_p95": round(float(np.percentile(lat[3:] or lat, 95)), 1),
    }
    print(json.dumps(summary, indent=2))
    print("learnt something" if summary["policy_mm"] < summary["hold_mm"] else
          "not better than holding still yet (more data / steps, or check preprocessing)")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        args.out.with_suffix(".json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
