# Robopoly Voice-Chat UX — PRD

Scope: frontend-only enhancements to the existing `static/index.html` +
`static/app.js` + `static/app.css` UI. No backend route changes; everything is
built on top of the existing endpoints.

External services consumed by the frontend:

| Concern              | Host             | Endpoint                                   |
| -------------------- | ---------------- | ------------------------------------------ |
| Game state + actions | `localhost:7999` | `/api/*` (REST + `/api/stream/game` WS)    |
| VLM inference        | `localhost:8000` | `POST /api/vlm/infer`                      |
| Whisper STT          | `localhost:8000` | `POST /api/whisper/transcribe`             |
| Robot joint states   | `localhost:8000` | WS `/api/stream/joint_states`              |
| Robot EEF pose       | `localhost:8000` | WS `/api/stream/eef_pose`, `/api/stream/eef_rpy` |

## 1. Goals

1. Treat the `Ask VLM → Query & response` panel as a live conversation, not
   a single text-in / text-out widget.
2. Replace the on-screen `Rec` button workflow with two hold-to-talk hotkeys:
   - **Z** — drives the VLM-as-player loop (rolls dice on your turn, picks a
     property action while a decision modal is open).
   - **X** — asks the VLM a free-form question about the *current state* of
     the robot or the game.
3. Surface the “whose turn is it” banner and every user/assistant utterance
   in the chat transcript so the operator can scroll back through the game.

## 2. Non-goals

- No backend changes. The existing `/api/whisper/transcribe`,
  `/api/vlm/infer`, `/api/vlm/system_prompt`, and game/dice/move/decide
  endpoints stay as-is.
- No change to the `System prompt` editor panel — only the
  `Query & response` panel is reshaped.
- No automatic text-to-speech output. The bot replies stay text-only.
- No support for arbitrary new property-decision verbs beyond the existing
  `buy / build / build_hotel / skip` JSON actions.

## 3. Feature breakdown

### 3.1 Chat-style Query & Response (features 2 + 4)

- Replace `#vlm-response` (single block) with `#vlm-chat`, a scrolling
  message column that renders each entry as a speech bubble:
  - `me` (right-aligned, accent fill) — user STT transcripts, typed prompts.
  - `bot` (left-aligned, panel fill) — VLM/agent replies.
  - `sys` (centered, muted) — turn-change announcements, status notes.
- The existing text input + `Ask` button still work and append a `me` bubble
  followed by a `bot` bubble (no behavioural change required for them; the
  user explicitly said “leave the on-screen mic button alone for now”).
- “It’s `<player>`’s turn” transitions emit a `sys` bubble each time the
  active player flips. The original `<div id="notification">` block under
  the board stays as-is — the chat panel mirrors the same string.
- Auto-scroll: when a new bubble appends, the chat column scrolls to bottom
  unless the user has manually scrolled up >40 px.

### 3.2 Z-hotkey: voice → immediate action (features 3 + 5)

Holding **Z** anywhere on the page starts mic capture; releasing **Z**
stops capture and pipes the audio through `/api/whisper/transcribe`.

- The transcript is appended to the chat as a `me` bubble.
- The transcript is then passed straight to `vlmPlayerAct(transcript)` —
  the existing single-agent function that emits the JSON action.
- This is the only consumer; the on-screen `Ask` button is *not* invoked.

State-dispatch rules (mirrors the existing `maybeAutoTriggerRobotTurn`):

| FSM state          | Behaviour                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------- |
| `TURN_START`       | Treat the voice as the user’s “nudge”. `vlmPlayerAct` will return `roll_and_move`.          |
| `AWAIT_DECISION`   | Voice describes the buy intent (“buy land”, “skip this one”, “buy hotel”). `vlmPlayerAct` returns `decide`. |
| any other          | Append a `sys` bubble “Ignored — wrong phase” and don’t dispatch.                            |

Why route through `vlmPlayerAct`: it already knows how to encode the game
state into the prompt, parse the JSON action, and call the existing
end-turn-chained `Roll dice` button or `submitDecision`. We get free reuse
of the auto-liquidation / jail / lap-cap flow.

Hotkey hygiene:

- Ignored when focus is inside a text input or textarea (so typing `z` in
  the `Ask` box still works).
- Ignored when the page is hidden (`document.hidden`).
- `keydown` auto-repeat is suppressed (we only act on the first press).

### 3.3 X-hotkey: voice → contextual Q&A (feature 6)

Holding **X** records, release transcribes via Whisper. The transcript is
appended as a `me` bubble. Then the frontend sends a `/api/vlm/infer` call
with **no JSON-action contract** — this is a free-form answer path, not the
agent path.

Context bundle attached to the prompt:

1. The full game-state snapshot (`buildVlmStateSummary(currentState)`).
2. A `robot` block sourced from the localhost:8000 WS streams:
   - `latest_joint_states` — last frame from `/api/stream/joint_states`.
   - `latest_eef_pose` — last frame from `/api/stream/eef_pose`.
   - `latest_eef_rpy` — last frame from `/api/stream/eef_rpy`.
3. The user’s transcribed question.

The frontend keeps three persistent WebSockets to the VLM server (opened on
boot, auto-reconnect with backoff). Each socket caches the most recent
frame in module-level variables — there is no polling, the X-hotkey just
reads the cached value when assembling the prompt.

System prompt for X-questions is a separate `client="robopoly_qa"` slot so
it doesn’t fight the agent-mode prompt the existing code installs at boot:

> You are a helpful, concise game-and-robot assistant for a Movensys-Monopoly
> demo. The user can ask about (a) the current state of the 6-DOF arm —
> joint angles in rad, EEF cartesian pose in m — and (b) the current
> game state, including why certain property decisions were made. Answer
> in plain prose (no JSON, no fences). Use 1–4 sentences. If the user asks
> about a property choice, ground your reasoning in the game state JSON
> (cash, owned properties, tier, distance, etc.) rather than guessing.

VLM response is rendered as a `bot` bubble.

### 3.4 Robot status WS subscriptions

- On page boot, after `setupVlm()`, call `setupRobotStateStream()`.
- Three sockets are opened in parallel: `eef_pose`, `eef_rpy`, `joint_states`.
- Each socket’s `onmessage` parses `{ data, error }` and updates a module-
  level cache only when `error == null` and `data != null`.
- `onclose` retries with exponential backoff (1 s → 2 s → 4 s, capped at 10 s).
- The cached values are exposed via `getRobotStateSnapshot()` for the X-key
  Q&A prompt assembly.

### 3.5 Interaction matrix

| Trigger              | Phase            | Effect                                      |
| -------------------- | ---------------- | ------------------------------------------- |
| Hold Z, release      | `TURN_START`     | Rolls + moves the active player.            |
| Hold Z, release      | `AWAIT_DECISION` | Buys / builds / skips current property.     |
| Hold X, release      | any              | Logs my question + bot answer in the chat.  |
| `Ask` button         | any              | Unchanged from today.                       |
| On-screen `Rec` mic  | any              | Unchanged from today.                       |

## 4. UI changes (concrete)

- `index.html`: replace `<div id="vlm-response"…>` and the small meta line
  underneath with a `<div id="vlm-chat" class="vlm-chat"></div>` plus a
  hidden meta strip (kept for ms/timestamp display under each bot bubble).
- `app.css`: add `.vlm-chat`, `.vlm-msg.me`, `.vlm-msg.bot`, `.vlm-msg.sys`,
  bubble shapes (rounded corners with the matching corner squared off),
  and a key-hint legend (`Z = act · X = ask`) above the chat column.
- `app.js`:
  - new module `chat` (functions `appendChat({role, text, meta})`,
    `clearChat()`, `chatScrollToBottom()`).
  - `announce()` keeps writing to the notification banner and *also*
    appends a `sys` bubble for turn changes.
  - new `setupHotkeys()` wiring Z + X with shared recorder helpers
    (factored out of the existing `setupVlm` mic logic — same MediaRecorder
    bootstrap, same transcribeBlob path).
  - new `setupRobotStateStream()` with the three-socket cache.
  - new `askVlmAboutState(question)` (X-key handler) that builds the
    state+robot context bundle and calls `/api/vlm/infer`.

## 5. Risks & open questions

- **Mic permission UX**: Z-key’s first press triggers the browser’s mic
  prompt and the user may release the key before granting permission. We
  handle this by setting a “armed” flag — if the prompt resolves after the
  key has already been released, we discard the recorder instead of
  starting an aborted capture.
- **Whisper for one-syllable utterances** (e.g. just “buy”) may return an
  empty string. Falling back to a `sys` bubble “Heard nothing — try again”
  keeps the loop usable.
- **Agent confusion on buy decisions**: the existing system prompt
  forbids prose, so voice transcripts like “buy hotel here” are folded
  into the `Context:` line of `vlmPlayerAct` and rely on the model to
  pick the matching `decide` JSON. This is the same risk that already
  exists for typed user nudges; no change in posture.
- **WS availability**: if localhost:8000 isn’t reachable, the joint /
  cartesian context will simply be `null`. The X-key Q&A still works
  for game-state questions; the system prompt acknowledges that
  robot fields may be missing.
- **Key collisions**: Z/X may collide with future keyboard shortcuts.
  The hotkeys are gated on `!isInputFocused() && !e.repeat`; users can
  always type in a textbox to escape capture.
