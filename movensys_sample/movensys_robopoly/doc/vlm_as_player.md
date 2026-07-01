# VLM as the robot player

The robot side of robopoly is driven by the orchestrator's VLM
(`movensys_vlm`, `:8000`). The browser at `localhost:7999` does **not**
play moves on its own — it converts game state into a prompt, asks the
VLM what to do, parses a single JSON action from the reply, and
dispatches that action through the existing `/api` endpoints.

No fine-tuning. The model's behavior is shaped entirely by the
**system prompt** the page installs once on first load (see §3).

---

## 1. Scope — what runs where

- `localhost:7999` (robopoly) — owns the game state, the robot arm
  (via `pick_and_place.py`), the property modal, and the VLM-agent
  loop in `static/app.js`. Nothing in this loop bypasses the rules
  engine; it just clicks the same buttons a human would.
- `localhost:8000` (orchestrator) — hosts `POST /api/vlm/infer` and
  the per-client system-prompt slot at `?client=robopoly`. Used as a
  black box; the agent loop only depends on those two endpoints.

## 2. Action protocol

Every reply from the VLM is parsed as **exactly one** JSON object.
Markdown fences (```json … ```) are tolerated; surrounding prose is
dropped. The parser picks the first balanced `{ … }` block.

Two actions are recognized:

### 2.1 `roll_and_move`

```json
{ "action": "roll_and_move", "player": "user" | "robot" }
```

Used when `state.fsm == "TURN_START"`. The frontend dispatches this
by clicking the Roll-dice button, which runs the spec §3 chain in
`game_logic.md`. The **dice step** branches on whose turn it is —
the move + end-turn steps are identical:

1. **Dice value** — picked by `currentState.turn`:
   - `state.turn == "user"` → `POST /api/dice/read_robot`. The human
     has already rolled the die by hand; the arm only moves to the
     dice scan pose so the camera has a clear view, then YOLO is
     read. **No pickup, no drop.** Submitted as `source="manual"`.
   - `state.turn == "robot"` → `POST /api/dice/roll_robot`. The arm
     physically picks up, lifts, and drops the die, retreats to the
     scan pose, then YOLO reads the rolled face. Submitted as
     `source="robot"`.
2. `POST /api/move/apply_robot` — arm drives the named player's
   cube to the destination tile; tile resolution runs server-side
   (rent / tax / chance / auto-liquidation / auto-jail PnP).
3. `POST /api/game/end_turn` — automatic when no Buy modal pops.

The VLM action itself does **not** change between turns — both
emit `roll_and_move` with the appropriate `player`. The frontend
picks read vs roll based on `currentState.turn`.

### 2.2 `decide`

```json
{ "action": "decide", "choice": "skip" | "buy" | "build" | "build_hotel" }
```

Used only when `state.decision_pending` is present (the player
landed on a buyable tile and the FSM is `AWAIT_DECISION`).

- `buy`         → buy land for $100
- `build`       → upgrade to house tier (delta = (2 − current_tier) × $100)
- `build_hotel` → upgrade to hotel tier (delta = (3 − current_tier) × $100)
- `skip`        → pass on the purchase

The decision goes through `POST /api/properties/{pid}/decide`,
followed by an automatic `POST /api/game/end_turn`.

### 2.3 Prompt envelope

Every call sends three things to the orchestrator's `/api/vlm/infer`:

- `image_b64:` — a JPEG snapshot of the on-screen **GAME BOARD** block
  captured client-side by `captureBoardImage()` in `static/app.js`.
  The capture composites the board background PNG with the `#pieces`
  SVG overlay (cubes + ownership circles) into a single canvas, then
  exports as base64 JPEG at quality 0.8. The orchestrator passes this
  string straight to `vlm_client.infer` without consulting any ROS
  topic.
  - `camera` is set to `"none"` in this case so the orchestrator
    doesn't also try to grab a physical-camera frame.
  - If the canvas capture fails (tainted canvas, no SVG element,
    etc.), the call falls back to `camera: "top"` so the agent still
    gets *some* visual grounding from the physical top-down camera.
    If that camera isn't publishing either, the orchestrator
    degrades to text-only and the JSON state alone drives the
    decision.
- `client: "robopoly"` — selects the per-client system-prompt slot
  (see §3).
- `prompt:` — the inlined action grammar (so the model can't drift
  back to a generic "vision assistant" role), followed by a context
  line and a JSON snapshot of game state:

```text
<user message>

State:
{
  "turn": "robot",
  "fsm": "TURN_START",
  "turn_number": 4,
  "positions": { "user": 5, "robot": 0 },
  "balances":  { "user": 1000, "robot": 1000 },
  "lap_count": { "user": 0, "robot": 0 },
  "last_dice": [3, 0],
  "last_dice_sum": 3,
  "properties_owned": {
    "user":  [ { "id": "boardfinal:seoul", "tile_index": 2, "tier": 1 } ],
    "robot": []
  },
  "decision_pending": null
}
```

`decision_pending` is omitted unless the FSM is `AWAIT_DECISION`; in
that case it carries `property_id`, `current_tier`, `max_tier`.

## 3. System prompt

On page load the agent installs its system prompt at
`PUT :8000/api/vlm/system_prompt?client=robopoly`. The installed text
has **two parts**:

1. A fixed agent preamble (`VLM_PLAYER_SYSTEM_PROMPT` in
   `static/app.js`) — defines the action grammar, the "you are NOT a
   vision assistant" rule, and example replies.
2. The **full authoritative game spec**, pulled from the robopoly
   backend at `GET :7999/api/game/rules` (which serves
   `doc/game_logic.md` verbatim as `text/markdown`). This way any
   edit to the spec doc — jail flow, IN_JAIL skip, auto-liquidation
   order, lap cap, etc. — auto-propagates into the agent's
   knowledge without code changes.

If `/api/game/rules` is unreachable (older server, stripped image),
the agent installs just the preamble plus a compact rules summary
inside it; the loop still works, only the verbose spec is missing.

The install **overwrites** any previous prompt in the slot — a stale
"vision assistant" prompt could otherwise cause the VLM to refuse
with "I cannot physically roll dice for you" instead of emitting an
action. To customize after boot, edit the textarea in the Ask VLM
sidebar (the PUT from the sidebar wins over the auto-install for the
rest of the session).

## 4. User turn (spec §4)

4.1. The user physically rolls the die by hand onto the dice scan area.
4.2. The user types into the **Ask VLM** textbox (any message —
     "I rolled" or "user just rolled the dice" both work) and presses
     Enter / Ask.
4.3. The frontend detects `state.turn == "user"`,
     `state.fsm == "TURN_START"` and routes the message through the
     agent loop instead of the normal free-form Q&A path.
4.4. The VLM replies with `{"action": "roll_and_move", "player": "user"}`.
     The frontend dispatches **the read-only dice path**
     (`/api/dice/read_robot`): the arm moves to the dice scan pose so
     the gripper is out of the camera's way, YOLO reads the face the
     human threw, then the red cube is driven to `(from + dice) % size`.
     The arm **never picks up or drops** the die on user turns.
4.5. If the arrival is a buyable tile, the Buy modal pops. The user
     clicks **Skip / Buy land / Buy + house / Buy + hotel** in the
     UI — *not* through the VLM. The user makes their own buy choices.
4.6. The turn ends automatically (either after auto-resolution, or
     immediately after `submitDecision` if the modal was shown).

> Outside `turn=user, fsm=TURN_START`, the Ask VLM textbox keeps its
> original free-form Q&A behavior — the agent loop does not steal
> non-turn messages.

## 5. Robot turn (spec §5)

5.1. When the WebSocket delivers any state event whose result is
     `turn=robot, fsm=TURN_START`, the frontend auto-prompts the VLM
     ("It's your turn (robot). Roll the dice and move your cube.").
5.2. The VLM replies with `{"action": "roll_and_move", "player": "robot"}`.
     The frontend dispatches **the full roll path** (`/api/dice/roll_robot`):
     the arm picks up the die at the scan pose, lifts it, drops it,
     retreats to clear the camera, then YOLO reads the rolled face.
     After that, the green cube is driven to `(from + dice) % size` —
     same move chain as the user turn, just with a different cube.
5.3. If the robot lands on a buyable tile, the frontend re-prompts
     the VLM with the decision_pending state. The VLM replies with a
     `decide` action and the frontend dispatches it. No human input.
5.4. The chain ends the turn automatically. Control returns to the
     user; the agent goes quiet until the next robot turn.

## 6. Idempotency

The auto-trigger is keyed by `(turn, fsm, turn_number, pending_pid)`
so a burst of WebSocket events during the robot's resolution does
not cause the VLM to be prompted multiple times for the same step. A
single in-flight guard (`vlmPlayerInFlight`) blocks reentrancy from
the user-turn path while the robot turn is mid-action and vice versa.

## 7. Failure modes

- VLM unreachable / 5xx → the prompt fails, the agent loop logs and
  exits without dispatching. The user can still click the Roll-dice
  button directly as a fallback (same chain, no VLM involvement).
- VLM emits unparseable text → `parseVlmAction` returns null; the
  loop logs the raw response and exits. Same fallback applies.
- VLM emits a `decide` action while the FSM is `TURN_START` (or vice
  versa) → the executor silently rejects mismatched actions because
  the underlying buttons are disabled outside their valid FSM.
- **`btn-roll-dice` is disabled when the VLM action arrives** — most
  common cause is `turnInFlight` stuck `true` from a prior failed
  chain (the `finally` block resets it, so this should only happen if
  the fsm landed in `AWAIT_DECISION` and the buy modal was dismissed
  without a `submitDecision`). `executeVlmAction` now logs:
  `[vlm-player] executeVlmAction: btn-roll-dice is disabled — action
  dropped.` followed by `{ fsm, turn, winner, turnInFlight }`. Reset
  via the Reset button or by clicking the buy modal.
- **Read mode — YOLO has no `dice_number` to publish** (e.g. the
  `yolo_dice_detector` node isn't running, the camera can't see the
  thrown die, or the user threw it outside the scan area). The script
  polls `/api/topics/dice_number` for up to `_READ_POLL_TIMEOUT_S` (8s
  by default), and if YOLO never returns a value it emits
  `DICE_NUMBER=1` as a fallback and logs a loud error with the last
  HTTP status + detail. The chain proceeds (red cube moves, turn ends,
  robot turn auto-starts) so the game doesn't dead-end on a silent
  502 — re-roll if the fallback face was wrong. The error log line
  starts with `read mode: YOLO never returned a usable dice_number`
  and is the right diagnostic for "robot didn't move after I typed".
- **Roll mode — YOLO can't see the dice after the drop** (gripper
  occlusion, camera fault). `_wait_for_rolled_dice_number` times out
  after `_DICE_POLL_TIMEOUT_S` (5s) past the post-settle window, then
  falls back to the latest cached `dice_number` so the chain still
  advances. Log line: `No fresh dice_number after drop — falling back
  to latest cached value`.
- **Cube pickup failed (`get_piece_info` + fallback search both
  miss)** — previously `pick_and_place.py` silently `return`ed with
  exit 0, so `apply_robot` advanced the game state while the physical
  cube never moved (board overlay teleported, real cube didn't). The
  script now `sys.exit(1)`, the router returns `502 PNP_FAILED`, and
  the frontend's catch logs `[roll-chain] aborted with error: ...`.
  `turnInFlight` resets cleanly in `finally`; re-trigger the turn
  after fixing the YOLO occlusion or repositioning the cube.

### 7.1 Diagnosing "robot didn't move after I typed"

The roll-dice chain prints to the browser console at every step. Open
DevTools → Console before clicking Ask, then check which line appears
last — that pinpoints where the chain stopped:

| Last line you see | Meaning |
|---|---|
| `[vlm-player] dispatching roll_and_move via btn-roll-dice click` | Click was issued. If nothing follows, the click handler bailed before any await — usually `turnInFlight` race. |
| `[vlm-player] executeVlmAction: btn-roll-dice is disabled — action dropped.` | Button gated; the attached state object says why. |
| `[roll-chain] dice step: {...}` (no response) | The dice subprocess hung. Check robopoly stdout for `read mode:` / roll-mode timing lines. |
| `[roll-chain] dice response: {...}` then `unexpected fsm: ...` | Server returned 200 but FSM wasn't `MOVING`. The response object shows what came back. |
| `[roll-chain] apply_robot: {...}` (no response) | Physical cube move is running; wait. |
| `[roll-chain] aborted with error: ...` | A fetch threw (502 from server, network). The error contains the HTTP detail — `DICE_NOT_DETECTED`, `PNP_FAILED`, etc. |

## 8. Code map

- `static/app.js`
  - `VLM_PLAYER_SYSTEM_PROMPT` — default prompt body (§3).
  - `vlmInferRaw`, `parseVlmAction`, `buildVlmStateSummary`,
    `executeVlmAction`, `vlmPlayerAct` — agent loop primitives.
  - `maybeAutoTriggerRobotTurn` — called from `refreshState` and
    the WS `hello` handler (§5).
  - `setupVlm.askOnce` — branches into `vlmPlayerAct` when
    `turn=user, fsm=TURN_START` (§4).
  - `ensureVlmPlayerSystemPrompt` — installs the default prompt on
    boot (§3).
- Backend endpoints used by the agent loop:
  - `POST /api/dice/read_robot` — user turn, read-only (no pickup).
  - `POST /api/dice/roll_robot` — robot turn, full pick + drop + read.
  - `POST /api/move/apply_robot`, `POST /api/properties/{pid}/decide`,
    `POST /api/game/end_turn` — unchanged.
- The two dice endpoints share `_spawn_dice_subprocess(mode, source)`
  in `router.py`. The 4th positional arg to `pick_and_place.py` is
  `"read"` (calls `_read_dice_only`) or `"roll"` (full chain).
