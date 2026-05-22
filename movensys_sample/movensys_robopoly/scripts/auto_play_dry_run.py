#!/usr/bin/env python3
"""Auto-play a full robopoly game end-to-end in dry-run mode.

Drives both user and robot turns by calling the robopoly REST API on
``:7999`` directly, bypassing the VLM agent loop (which would otherwise
need ``movensys_vlm`` + vLLM on ``:8000`` to be running). On the user
side this is the same chain that ``"user just rolled the dice"`` would
trigger through the Ask-VLM textbox: ``/api/dice/read_robot`` (arm to
scan pose, YOLO read) → ``/api/move/apply_robot`` (cube to destination)
→ ``/api/properties/{pid}/decide`` (if a buyable tile pops the modal)
→ ``/api/game/end_turn``.

Requirements:
- Start the robopoly server with ``MOVENSYS_PNP_DRY_RUN=1`` so
  ``pick_and_place.py`` short-circuits to random dice + no arm motion.
- ``movensys_vlm`` does NOT need to be running.

Decision policy: uniform random over the legal action set
({skip, buy, build, build_hotel}) gated by ``current_tier``,
``max_tier``, and the current player's liquid balance.

Chance tiles: the VLM-driven ``/api/game/chance_card`` flow is skipped
(it needs ``:8000``). The rules engine left the FSM at RESOLVE_TILE so
``end_turn`` works; the ±$100/$200 delta simply isn't applied. Surfaced
in logs as ``chance tile: skipping VLM card flow``.

Stops when the engine reaches GAME_OVER (bankruptcy per spec §6.1 or
the 5-lap cap per §6.2), or when ``--max-turns`` is hit.

Concurrency: the script is tolerant of a browser tab open at
``localhost:7999`` racing it (the page auto-triggers robot turns through
the VLM). Each turn waits for FSM to stabilize at TURN_START; if the
dice value is already in the server (FSM=MOVING when we POSTed), we
adopt it and continue with apply_move. Close the tab for cleaner runs.

Usage:
    # Terminal A — start the server in dry-run.
    cd movensys_sample/movensys_robopoly
    MOVENSYS_PNP_DRY_RUN=1 python3 -m uvicorn main:app \\
        --host 127.0.0.1 --port 7999

    # Terminal B — auto-play a full game.
    python3 scripts/auto_play_dry_run.py --seed 42
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from typing import Any

import requests

DEFAULT_BASE = "http://localhost:7999"
TILE_COUNT = 14          # board_final.json: 14-tile counter-clockwise loop
LAND_PRICE = 100         # spec §4.1: Land tier (also utility flat price)
TIER_PRICE = 100         # spec §4.1.2: $100 per tier crossed on upgrade

log = logging.getLogger("auto_play")


class AutoPlayError(RuntimeError):
    pass


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.session = requests.Session()

    def get(self, path: str) -> dict[str, Any]:
        r = self.session.get(f"{self.base}{path}", timeout=10)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        # Long timeout because /dice/{read,roll}_robot waits on the
        # pick_and_place subprocess. In dry-run it returns near-instantly,
        # but we leave headroom for real-hardware reuse.
        r = self.session.post(f"{self.base}{path}", json=payload or {}, timeout=180)
        r.raise_for_status()
        return r.json()


def _choose_action(current_tier: int, max_tier: int, balance: int,
                   rng: random.Random) -> str:
    """Uniformly pick an action from the legal set for this modal.

    Legal options gated by:
    - max_tier (utility caps at 1, property caps at 3)
    - current_tier (can't downgrade)
    - liquid balance (must cover the delta)
    """
    options = ["skip"]
    if max_tier >= 1 and current_tier < 1 and balance >= LAND_PRICE:
        options.append("buy")
    if max_tier >= 2 and current_tier < 2 and balance >= (2 - current_tier) * TIER_PRICE:
        options.append("build")
    if max_tier >= 3 and current_tier < 3 and balance >= (3 - current_tier) * TIER_PRICE:
        options.append("build_hotel")
    return rng.choice(options)


def _handle_decision(client: Client, move_resp: dict[str, Any],
                     rng: random.Random) -> None:
    """If the move resolution opened a buy modal, decide and submit it."""
    for tile in move_resp.get("resolved", {}).get("tiles", []):
        if not tile.get("needs_decision"):
            continue
        payload = tile.get("payload", {})
        pid = payload.get("property_id")
        if pid is None:
            log.warning("decision tile without property_id: %s", tile)
            continue
        current_tier = int(payload.get("current_tier", 0))
        max_tier = int(payload.get("max_tier", 1))
        state = client.get("/api/game/state")
        balance = int(state["players"][state["turn"]]["balance"])
        action = _choose_action(current_tier, max_tier, balance, rng)
        log.info(
            "  decide: %s tier=%d/%d cash=$%d -> %s",
            pid, current_tier, max_tier, balance, action,
        )
        client.post(f"/api/properties/{pid}/decide", {"action": action})


def _summarize(state: dict[str, Any]) -> str:
    bal = state.get("players", {})
    pos = state.get("positions", {})
    laps = state.get("lap_count", {})
    return (
        f"u@{pos.get('user')} ${bal.get('user', {}).get('balance')} lap={laps.get('user', 0)} | "
        f"r@{pos.get('robot')} ${bal.get('robot', {}).get('balance')} lap={laps.get('robot', 0)}"
    )


def _resolve_pending_decision(client: Client, state: dict[str, Any],
                              rng: random.Random) -> None:
    """Resolve an AWAIT_DECISION that a racing client opened but won't
    close (browser's user-turn buy modal never auto-clicks). Look up the
    property at the current player's tile and submit a random decision.
    """
    turn = state["turn"]
    tile_index = state["positions"][turn]
    # /api/properties returns every PropertyState plus its static Tile card.
    props = client.get("/api/properties")
    target = next((p for p in props if p.get("tile_index") == tile_index), None)
    if target is None:
        log.warning("no property at tile_index=%d for %s", tile_index, turn)
        return
    pid = target["id"]
    # Tier: 3 if has_hotel, 2 if houses > 0, 1 if owned, else 0.
    if target.get("has_hotel"):
        current_tier = 3
    elif target.get("houses", 0) > 0:
        current_tier = 2
    elif target.get("owner"):
        current_tier = 1
    else:
        current_tier = 0
    max_tier = 1 if target.get("kind") == "utility" else 3
    balance = int(state["players"][turn]["balance"])
    action = _choose_action(current_tier, max_tier, balance, rng)
    log.info(
        "  race-decide: %s tier=%d/%d cash=$%d -> %s",
        pid, current_tier, max_tier, balance, action,
    )
    client.post(f"/api/properties/{pid}/decide", {"action": action})


def _wait_for_turn_start(client: Client, rng: random.Random,
                         timeout_s: float = 30.0) -> dict[str, Any]:
    """Poll until FSM settles at TURN_START or GAME_OVER. Tolerates a
    racing browser tab whose previous robot-turn drive is still
    finishing. If a race left the FSM stuck at AWAIT_DECISION (browser
    opened a user-turn buy modal it won't auto-close), resolve it.
    """
    deadline = time.time() + timeout_s
    last_fsm: str | None = None
    while time.time() < deadline:
        state = client.get("/api/game/state")
        fsm = state["fsm"]
        if fsm in ("TURN_START", "GAME_OVER"):
            return state
        if fsm == "AWAIT_DECISION":
            log.warning("  race stuck at AWAIT_DECISION; resolving")
            _resolve_pending_decision(client, state, rng)
            # Decision drops fsm back to RESOLVE_TILE — end_turn handles
            # the rest. Loop continues; we'll see RESOLVE_TILE next tick.
            state2 = client.get("/api/game/state")
            if state2["fsm"] in ("RESOLVE_TILE", "END_TURN"):
                client.post("/api/game/end_turn")
            continue
        if fsm != last_fsm:
            log.info("  waiting for TURN_START (fsm=%s)", fsm)
            last_fsm = fsm
        time.sleep(0.5)
    raise AutoPlayError(f"timed out waiting for TURN_START (stuck at fsm={last_fsm})")


def play_one_turn(client: Client, rng: random.Random) -> bool:
    """Drive exactly one turn. Returns False once the game is over."""
    state = _wait_for_turn_start(client, rng)
    if state["fsm"] == "GAME_OVER":
        return False
    turn = state["turn"]
    turn_no = int(state.get("turn_number", 0))
    log.info("turn %s — %s [%s]", turn_no, turn, _summarize(state))

    # 1. Dice. User turn = read-only (no pickup); robot turn = full roll.
    #    Both short-circuit to random.randint(1, 6) under MOVENSYS_PNP_DRY_RUN.
    #    expected_turn_number guards against the browser's roll-and-move
    #    chain straddling a turn boundary (server returns 409 STALE_TURN).
    dice_ep = "/api/dice/read_robot" if turn == "user" else "/api/dice/roll_robot"
    try:
        dice_resp = client.post(dice_ep, {
            "is_YOLO": False,
            "expected_turn_number": turn_no,
        })
        dice_n = dice_resp.get("dice_number")
        log.info("  rolled %s", dice_n)
    except requests.HTTPError as exc:
        # If a racing client already submitted the dice we land in
        # fsm=MOVING (or further). Refresh state and adopt whatever's
        # there rather than fighting.
        body = exc.response.text if exc.response is not None else ""
        if exc.response is not None and exc.response.status_code == 409 and "fsm=" in body:
            log.warning("  dice race detected (%s); adopting server state", body.strip())
        else:
            raise

    # Re-read state: jail-skip path (spec §4.5.2.2) leaves FSM at
    # END_TURN with no move to apply.
    state = client.get("/api/game/state")
    if state["fsm"] == "END_TURN":
        log.info("  jail-skipped — ending turn")
        client.post("/api/game/end_turn")
        return True
    # If a racing client already ran apply_move, we may be past MOVING.
    # Bail back to the outer loop — the TURN_START wait will catch up.
    if state["fsm"] in ("RESOLVE_TILE", "AWAIT_DECISION", "GAME_OVER"):
        log.warning("  race: another client is mid-turn (fsm=%s); skipping", state["fsm"])
        return state["fsm"] != "GAME_OVER"

    # 2. Apply move. The server already adjusted last_dice_sum for the
    #    IN_JAIL skip rule (spec §4.5.4), so we just trust it.
    from_tile = state["positions"][turn]
    dice_sum = state["last_dice_sum"]
    to_tile = (from_tile + dice_sum) % TILE_COUNT
    try:
        move_resp = client.post("/api/move/apply_robot", {
            "player": turn,
            "from_tile": from_tile,
            "to_tile": to_tile,
            "is_YOLO": False,
            "expected_turn_number": turn_no,
        })
    except requests.HTTPError as exc:
        body = exc.response.text if exc.response is not None else ""
        if exc.response is not None and exc.response.status_code == 409:
            log.warning("  apply_move race (%s); refreshing state", body.strip())
            move_resp = {"resolved": {"tiles": []}}
        else:
            raise
    resolved = move_resp.get("resolved", {}).get("tiles", [])
    if resolved:
        log.info("  resolved: %s",
                 [f"{r.get('kind')}@{r.get('tile_index')}" for r in resolved])

    # 3. Property decision modal (the only place the chain pauses).
    _handle_decision(client, move_resp, rng)

    # 4. Bankruptcy-driven game over surfaces here (spec §6.1).
    state = client.get("/api/game/state")
    if state["fsm"] == "GAME_OVER":
        return False

    # 5. Chance tile: the spec defers the money outcome to the VLM-driven
    #    /api/game/chance_card flow (router.py). Skip it in dry-run.
    if any(t.get("kind") == "chance_drawn" for t in resolved):
        log.info("  chance tile: skipping VLM card flow (dry-run, no orchestrator)")

    # 6. End the turn. Lap-cap check (spec §6.2) runs server-side here.
    if state["fsm"] in ("RESOLVE_TILE", "END_TURN"):
        client.post("/api/game/end_turn")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-play a full robopoly game in dry-run mode.",
    )
    parser.add_argument("--base", default=os.environ.get("ROBOPOLY_BASE", DEFAULT_BASE),
                        help=f"robopoly base URL (default: {DEFAULT_BASE})")
    parser.add_argument("--seed", type=int, default=None,
                        help="seed the decision RNG (auto-derived per run when --runs > 1)")
    parser.add_argument("--max-turns", type=int, default=300,
                        help="hard cap on turns played per game (safety net)")
    parser.add_argument("--no-reset", action="store_true",
                        help="continue an in-progress game instead of starting fresh")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to sleep between turns (default: 0)")
    parser.add_argument("--runs", type=int, default=1,
                        help="play N complete games back-to-back, "
                             "resetting between each (default: 1)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    client = Client(args.base)
    log.info("connecting to %s", client.base)
    try:
        client.get("/api/health")
    except requests.RequestException as exc:
        log.error("server not reachable at %s: %s", client.base, exc)
        return 2

    results: list[dict[str, Any]] = []
    overall_start = time.perf_counter()
    for run_i in range(1, args.runs + 1):
        # Per-run seed: deterministic across runs when --seed is set, but
        # each run gets a distinct stream so the games aren't identical.
        per_run_seed = (args.seed + run_i - 1) if args.seed is not None else None
        rng = random.Random(per_run_seed)
        if args.runs > 1:
            log.info("========== run %d / %d (seed=%s) ==========",
                     run_i, args.runs, per_run_seed)

        if run_i > 1 or not args.no_reset:
            log.info("starting fresh game (board=final)")
            client.post("/api/game/start", {"board": "final"})

        run_start = time.perf_counter()
        outcome: dict[str, Any] = {"run": run_i, "seed": per_run_seed}
        try:
            for turn_i in range(args.max_turns):
                cont = play_one_turn(client, rng)
                if not cont:
                    state = client.get("/api/game/state")
                    elapsed = time.perf_counter() - run_start
                    log.info(
                        "GAME OVER after %d turns in %.1fs — "
                        "winner=%s, balances=%s, laps=%s",
                        state.get("turn_number"), elapsed, state.get("winner"),
                        {p: state["players"][p]["balance"]
                         for p in ("user", "robot")},
                        state.get("lap_count"),
                    )
                    outcome.update({
                        "ok": True,
                        "winner": state.get("winner"),
                        "turns": state.get("turn_number"),
                        "elapsed_s": elapsed,
                    })
                    break
                if args.delay:
                    time.sleep(args.delay)
            else:
                log.warning("max-turns=%d reached without a winner",
                            args.max_turns)
                outcome.update({"ok": False, "reason": "max_turns"})
        except requests.HTTPError as exc:
            body = exc.response.text if exc.response is not None else ""
            log.error("HTTP error: %s — %s", exc, body)
            outcome.update({"ok": False, "reason": f"http {exc}"})
        except AutoPlayError as exc:
            log.error("auto-play aborted: %s", exc)
            outcome.update({"ok": False, "reason": str(exc)})

        results.append(outcome)
        # Bail the multi-run loop on the first failure — the user wants
        # to fix bugs before continuing.
        if not outcome.get("ok"):
            log.error("aborting --runs sweep at run %d/%d", run_i, args.runs)
            break

    # Summary
    if args.runs > 1:
        ok_runs = [r for r in results if r.get("ok")]
        log.info("==================== summary ====================")
        log.info("completed %d / %d runs in %.1fs",
                 len(ok_runs), args.runs, time.perf_counter() - overall_start)
        for r in results:
            if r.get("ok"):
                log.info(
                    "  run %d: winner=%s in %d turns (%.1fs)",
                    r["run"], r["winner"], r["turns"], r["elapsed_s"],
                )
            else:
                log.info("  run %d: FAILED — %s", r["run"], r.get("reason"))
        wins = {"user": 0, "robot": 0, None: 0}
        for r in ok_runs:
            wins[r.get("winner")] = wins.get(r.get("winner"), 0) + 1
        log.info("  wins: user=%d robot=%d draws=%d",
                 wins["user"], wins["robot"], wins[None])
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
