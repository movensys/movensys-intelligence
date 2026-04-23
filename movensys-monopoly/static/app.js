/**
 * Board 3 viewer + manual control panel.
 * Subscribes to /api/stream/game for live events, reconciles from
 * /api/game/state on (re)connect. Piece positions use tile-center
 * coordinates mapped per board.
 */

const BOARD_LAYOUTS = {
  // tile index -> {cx, cy} center in SVG viewBox units (300x500 for Board 3)
  "3": (() => {
    const centers = {};
    centers[0] = { cx: 250, cy: 450 };
    centers[1] = { cx: 150, cy: 450 };
    centers[2] = { cx: 50,  cy: 450 };
    centers[3] = { cx: 50,  cy: 350 };
    centers[4] = { cx: 50,  cy: 250 };
    centers[5] = { cx: 50,  cy: 150 };
    centers[6] = { cx: 50,  cy: 50  };
    centers[7] = { cx: 150, cy: 50  };
    centers[8] = { cx: 250, cy: 50  };
    centers[9] = { cx: 250, cy: 150 };
    centers[10] = { cx: 250, cy: 250 };
    centers[11] = { cx: 250, cy: 350 };
    return centers;
  })(),
};

async function fetchJson(path, init) {
  const r = await fetch(path, init);
  if (!r.ok) throw new Error(`${path} -> ${r.status} ${await r.text()}`);
  return r.json();
}

async function postJson(path, body) {
  return fetchJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function modeBadge(label, health) {
  const mode = health.mode || (health.enabled ? "on" : "off");
  const cls = ["live", "on"].includes(mode) ? mode : "stub";
  return `<span class="badge ${cls}"><span class="dot"></span>${label}:${mode}</span>`;
}

async function refreshBadges() {
  try {
    const [stt, llm, robot, ros2] = await Promise.all([
      fetchJson("/api/stt/health"),
      fetchJson("/api/llm/health"),
      fetchJson("/api/robot/health"),
      fetchJson("/api/ros2/health"),
    ]);
    document.getElementById("modes").innerHTML =
      modeBadge("STT", stt) + modeBadge("LLM", llm) +
      modeBadge("Robot", robot) + modeBadge("ROS2", ros2);
  } catch (err) {
    console.warn("badge refresh failed:", err);
  }
}

async function loadBoardSvg(boardId) {
  const host = document.getElementById("board-host");
  const url = boardId === "3" ? "/assets/boards/board3_blank.svg" : null;
  if (!url) { host.innerHTML = `<div class="muted">Board ${boardId} visual TBD</div>`; return; }
  const r = await fetch(url);
  host.innerHTML = await r.text();
}

function movePiece(player, tileIndex, boardId) {
  const layout = BOARD_LAYOUTS[boardId];
  if (!layout) return;
  const c = layout[tileIndex];
  if (!c) return;
  const el = document.getElementById(`piece-${player}`);
  el.setAttribute("cx", c.cx);
  el.setAttribute("cy", c.cy);
  // Stagger the two pieces so they don't overlap when co-located.
  if (player === "robot") el.setAttribute("transform", "translate(-28 0)");
}

function renderState(state) {
  document.getElementById("st-fsm").textContent = state.fsm;
  document.getElementById("st-turn").textContent = state.turn;
  document.getElementById("st-num").textContent = state.turn_number;
  document.getElementById("st-winner").textContent = state.winner || "—";
  const ld = state.last_dice;
  document.getElementById("st-dice").textContent =
    ld ? `${ld[0]} + ${ld[1]} = ${state.last_dice_sum}` : "—";
  for (const p of ["user", "robot"]) {
    const pos = state.positions[p];
    if (pos !== undefined) movePiece(p, pos, state.board_id);
  }
  const winner = state.winner;
  document.getElementById("btn-apply-move").disabled = state.fsm !== "MOVING";
  document.getElementById("btn-submit-dice").disabled = state.fsm !== "TURN_START";
  document.getElementById("btn-end-turn").disabled =
    !["RESOLVE_TILE", "END_TURN"].includes(state.fsm) || winner;
}

function logEvent(env) {
  const ol = document.getElementById("event-log");
  const li = document.createElement("li");
  li.className = `type-${env.type}`;
  const ts = env.ts ? env.ts.slice(11, 19) : "";
  li.innerHTML = `<span class="ts">${ts}</span>${env.type} ${JSON.stringify(env.payload)}`;
  ol.prepend(li);
  while (ol.children.length > 50) ol.removeChild(ol.lastChild);
}

let currentState = null;

async function refreshState() {
  currentState = await fetchJson("/api/game/state");
  renderState(currentState);
}

function openStream() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/stream/game`);
  ws.onmessage = async (ev) => {
    const env = JSON.parse(ev.data);
    logEvent(env);
    if (env.type === "hello" && env.payload.snapshot) {
      currentState = env.payload.snapshot;
      renderState(currentState);
      return;
    }
    // Reconcile from REST rather than patching piecemeal — keeps the UI in sync
    // with the server's authoritative state under event drops.
    await refreshState();
  };
  ws.onclose = () => setTimeout(openStream, 1500);
  ws.onerror = () => ws.close();
}

// --- manual controls -------------------------------------------------------

document.getElementById("btn-start").addEventListener("click", async () => {
  const board = document.getElementById("board-select").value;
  await loadBoardSvg(board);
  await postJson("/api/game/start", { board });
  await refreshState();
});

document.getElementById("btn-submit-dice").addEventListener("click", async () => {
  const value = parseInt(document.getElementById("dice-input").value, 10);
  await postJson("/api/dice/submit", { value, source: "manual" });
});

document.getElementById("btn-apply-move").addEventListener("click", async () => {
  if (!currentState || !currentState.last_dice_sum) return;
  const player = currentState.turn;
  const from = currentState.positions[player];
  const size = currentState.board_id === "3" ? 12
            : currentState.board_id === "1" ? 20 : 40;
  const to = (from + currentState.last_dice_sum) % size;
  try {
    await postJson("/api/move/apply", { player, from_tile: from, to_tile: to });
  } catch (err) {
    console.warn("apply_move:", err);
  }
});

document.getElementById("btn-end-turn").addEventListener("click", async () => {
  await postJson("/api/game/end_turn");
});

// --- boot ------------------------------------------------------------------

(async () => {
  await refreshBadges();
  setInterval(refreshBadges, 5000);
  await loadBoardSvg("3");
  await refreshState();
  openStream();
})();
