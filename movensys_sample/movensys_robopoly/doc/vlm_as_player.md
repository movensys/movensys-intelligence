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
`game_logic.md`:

1. `POST /api/dice/roll_robot` — arm picks the die, drops it,
   YOLO reads the face value.
2. `POST /api/move/apply_robot` — arm drives the named player's
   cube to the destination tile; tile resolution runs server-side
   (rent / tax / chance / auto-liquidation / auto-jail PnP).
3. `POST /api/game/end_turn` — automatic when no Buy modal pops.

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

- `camera: "top"` — the orchestrator grabs the latest `/image_top/rgb`
  frame from the top-down board camera and attaches it as image
  grounding. If the camera is not publishing, the orchestrator silently
  degrades to text-only (no error, the JSON state still drives the
  decision).
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

4.1. The user physically rolls the die.
4.2. The user types into the **Ask VLM** textbox (any message —
     "I rolled" works) and presses Enter / Ask.
4.3. The frontend detects `state.turn == "user"`,
     `state.fsm == "TURN_START"` and routes the message through the
     agent loop instead of the normal free-form Q&A path.
4.4. The VLM replies with `{"action": "roll_and_move", "player": "user"}`.
     The frontend dispatches: arm picks/drops the die at the dice
     scan position, reads the YOLO face value, then drives the
     red cube to `(from + dice) % size`.
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
     The frontend runs the same chain as §4.4 with the green cube.
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
- No backend changes. All actions reuse:
  `POST /api/dice/roll_robot`, `POST /api/move/apply_robot`,
  `POST /api/properties/{pid}/decide`, `POST /api/game/end_turn`.
