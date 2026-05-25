# API surface of `movensys_robopoly`

This doc enumerates every API the robopoly stack exposes or consumes, and
how the pieces are wired together.

robopoly is uvicorn-served on `:7999` (host-side, not Docker). The browser
makes two kinds of calls from `http://localhost:7999/`:

1. **Same-origin** to robopoly's own backend at `:7999`.
2. **Cross-origin** to the `movensys_vlm` orchestrator at `:8000` (via
   `VLM_BASE = http://localhost:8000` in `static/app.js`).

All robot motion ultimately goes through the orchestrator — the
`pick_and_place.py` subprocess is itself an HTTP client of `:8000`, so the
"robopoly only talks to `movensys_vlm` via its API" rule holds end-to-end.

---

## 1. Browser → robopoly backend (`:7999`)

### Health / adapter mode

- `GET /api/health` — liveness probe.
- `GET /api/robot/health` — reports `RobotAdapter` mode (`live` / `stub`,
  derived from `MOVENSYS_VLM_URL` env). **No network call** — just reads
  the env var.
- `GET /api/stt/health` — same for `STTAdapter`.
- `GET /api/vlm/health` — same for `VLMAdapter`.
- `GET /api/modes` — aggregates all three.

> The `mode=live` badge only confirms `MOVENSYS_VLM_URL` is set, not that
> the orchestrator is reachable. The **Ask** button is the real
> reachability test.

### Game state

- `GET /api/game/state` — full FSM / positions / money / properties
  snapshot. Read from in-memory `GameManager`.
- `POST /api/game/start` — start a board; emits `game_started` on the
  event bus.
- `POST /api/game/end_turn` — flip turn; emits `fsm_transition`.
- `GET /api/game/winner` — current winner or `null`.
- `POST /api/game/config` — patch `RuntimeConfig` (`dice_source`,
  `auctions_enabled`, `income_tax_mode`, `player_colors`, `is_YOLO`).
- `POST /api/game/save_state` — writes the current snapshot to
  `saved_status.yaml` on disk.
- `POST /api/game/load_state` — reads `saved_status.yaml` and replaces
  state.
- `GET /api/game/next_prompt` — M1 stub hint string.
- `GET /api/game/rules` — returns `doc/game_logic.md` verbatim as
  `text/markdown`. Used by the VLM-player agent loop to seed the
  system prompt with the authoritative spec on every page load
  (see `vlm_as_player.md` §3).

### Dice / move

- `POST /api/dice/request` — mark dice-request (in-memory).
- `POST /api/dice/submit` — submit manual / RNG dice value (in-memory).
- `POST /api/dice/roll_robot` — spawns `pick_and_place.py dice GO <is_YOLO>`
  as a subprocess. Parses `DICE_NUMBER=N` from its stdout, then calls
  `submit_dice(N, "robot")`. The subprocess itself drives the arm via the
  orchestrator's HTTP API (see §3).
- `POST /api/move/apply` — apply move (in-memory).
- `POST /api/move/apply_robot` — spawns `pick_and_place.py <cube> <board_pos>
  <is_YOLO>`, waits for it to finish, then calls `apply_move`. Subprocess
  drives the arm via the orchestrator.

### Properties

- `GET /api/properties`
- `GET /api/properties/{pid}`
- `POST /api/properties/{pid}/decide` — accept / skip / build on arrival.
- `POST /api/properties/{pid}/buy`
- `POST /api/properties/{pid}/build`
- `POST /api/properties/{pid}/mortgage`
- `POST /api/properties/{pid}/unmortgage`
- `POST /api/properties/{pid}/sell_building`

### Money

- `GET /api/money` — balances snapshot.
- `GET /api/money/{player}` — single balance.

### Effects (debug)

- `POST /api/effects/{effect_type}` — apply a Chance / Community Chest
  effect manually.

### WebSocket event streams

All four read from the in-memory `EventBus`:

- `WS /api/stream/game` — every event.
- `WS /api/stream/board` — board events only (`move_applied`,
  `lap_completed`, `fsm_transition`, `game_started`, `game_won`).
- `WS /api/stream/money` — money / property-payment events.
- `WS /api/stream/properties` — property-state events.

---

## 2. Browser → `movensys_vlm` orchestrator (`:8000`)

The Ask VLM widget, mic, memory counter, and system-prompt editor all
bypass robopoly's backend and hit the orchestrator directly.

### VLM inference

- `POST /api/vlm/infer` — fired by the **Ask** button and by the
  VLM-player agent loop. Body includes `client: "robopoly"` so the
  orchestrator reads the per-client system prompt slot.
  Image source (one of):
  - `image_b64: "<base64-jpeg>"` (+ `camera: "none"`) — caller-supplied
    image; the orchestrator skips ROS lookup entirely. The agent loop
    sends a screenshot of the on-screen GAME BOARD block via this
    path (see `vlm_as_player.md` §2.3).
  - `camera: "top" | "hand"` — orchestrator grabs the latest ROS RGB
    frame and uses that.
  - `camera: "none"` (no `image_b64`) — text-only inference.
  On the orchestrator side this call triggers:
  - `memory_client.recall(prompt)` → TEI embedder `:9020` + Qdrant `:6333`
    (search for related past Q&A pairs to inject into the system prompt).
  - vLLM `:9000` — actual chat completion.
  - `memory_client.store(Q+A)` → TEI `:9020` + Qdrant `:6333` (persist
    this turn for future recall).

### System prompt (per-client)

The orchestrator keeps a separate prompt slot per `client` key
(`"robopoly"`, `"vlm"`, `"default"`). robopoly's UI always passes
`?client=robopoly` so its textarea is isolated from `/vlm`'s.

- `GET /api/vlm/system_prompt?client=robopoly` — fired on page load to
  populate the textarea.
- `PUT /api/vlm/system_prompt?client=robopoly` — **Save**.
- `DELETE /api/vlm/system_prompt?client=robopoly` — **Reset**.

### Speech-to-text

- `POST /api/whisper/transcribe` — multipart upload from the **Rec**
  button; the orchestrator forwards audio to the Whisper service
  `:9010` and returns `{"text": "..."}`.

### Memory (vector DB)

- `GET /api/vlm/memory` — counter polls this every 5 s and right after
  every Ask. Returns `{count, enabled}` from Qdrant `:6333`.
- `DELETE /api/vlm/memory` — **Clear memory** button. Drops the Qdrant
  collection.

---

## 3. `pick_and_place.py` (subprocess spawned by §1) → orchestrator (`:8000`)

The dice/move subprocess is an HTTP client of `movensys_vlm`. It does
not touch ROS2 directly. The base URL is hard-coded:

```python
URL = "http://localhost:8000"
```

### Motion

- `POST /api/move/absolute_cartesian_base`
- `POST /api/move/relative_cartesian_base`
- `POST /api/move/relative_cartesian_tool`
- `POST /api/move/absolute_joint_pose`
- `POST /api/move/joint_absolute`
- `POST /api/move/joint_relative`

### Services / config

- `POST /api/services/gripper`
- `GET  /api/services/get_eef_pose`
- `POST /api/config/scales`

### ROS topic snapshots (read-only)

- `GET /api/topics/yolo_tf` — YOLO-detected piece poses.
- `GET /api/topics/{piece_1|piece_2|dice|…}` — per-object pose snapshot.
- `GET /api/topics/dice_number` — YOLO-detected dice face value
  (`/yolo_dice_detector/dice_number`). This is what the subprocess
  prints as `DICE_NUMBER=N` so robopoly can pick it up.

---

## 4. Adapters in `adapters/` — wired but health-only

`adapters/vlm.py`, `adapters/stt.py`, and `adapters/robot.py` all point
at `MOVENSYS_VLM_URL` and expose `.infer()` / `.transcribe()` /
`.gripper()` / etc. methods, but **only their `.health()` is currently
called** (from `/api/*/health` and `/api/modes`). No game-logic code path
calls the methods; the real motion path is the `pick_and_place.py`
subprocess described in §3.

---

## 5. Service topology recap

```
browser ─ same-origin ─► robopoly :7999 ─► subprocess (pick_and_place.py)
                              │                       │
                              │                       └─► orchestrator :8000 (HTTP)
                              │
                              └─► saved_status.yaml on disk

browser ─ cross-origin ─► orchestrator :8000
                                ├─► vLLM    :9000
                                ├─► Whisper :9010
                                ├─► TEI     :9020
                                ├─► Qdrant  :6333
                                └─► ROS2 (cameras, IK, gripper) via ros2_node.py
```

robopoly never imports `rclpy`; every ROS interaction is mediated by the
orchestrator's HTTP API.
