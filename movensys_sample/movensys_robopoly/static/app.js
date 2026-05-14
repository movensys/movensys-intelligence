/**
 * movensys-monopoly UI.
 *
 * 14-tile JSON model rendered on a 14-cell rectangular perimeter (5 wide × 4
 * tall grid). Indexing is counter-clockwise from GO at the bottom-left
 * corner. The viewBox matches board.png (1261×584 ≈ 2.16:1).
 */

// Cell geometry, corners 1.5× side cells:
//   width  units: 1.5 + 1 + 1 + 1 + 1.5 = 6 → unit ≈ 210.17
//   height units: 1.5 + 1 + 1 + 1.5     = 5 → unit ≈ 116.8
//   corner ≈ 315×175, top/bot side ≈ 210×175, left/right side ≈ 315×117
const BOARD_FINAL_LAYOUT = {
  viewBox: { w: 1261, h: 584 },
  centers: {
    0:  { user: [61.70,   531.05], robot: [135.03,  531.05] },  // GO (BL)
    1:  { user: [54.10,   384.18], robot: [123.63,  383.32] },  // SUWON (left, lower mid)
    2:  { user: [51.57,   242.38], robot: [119.83,  242.78] },  // SEOUL (left, upper mid)
    3:  { user: [52.83,   99.32],  robot: [118.57,  98.45]  },  // IN JAIL (TL)
    4:  { user: [298.45,  106.91], robot: [365.45,  106.05] },  // ELECTRIC COMPANY (top)
    5:  { user: [546.61,  105.65], robot: [611.07,  104.78] },  // JEONJU (top)
    6:  { user: [803.62,  105.65], robot: [870.62,  104.78] },  // DAEJEON (top)
    7:  { user: [1049.24, 108.18], robot: [1114.97, 107.31] },  // NON-FREE PARKING (TR)
    8:  { user: [1050.51, 243.65], robot: [1114.97, 244.05] },  // GYEONGJU (right, upper mid)
    9:  { user: [1051.77, 385.45], robot: [1114.97, 384.58] },  // BUSAN (right, lower mid)
    10: { user: [1051.77, 536.11], robot: [1117.51, 536.51] },  // GO TO JAIL (BR)
    11: { user: [801.09,  536.11], robot: [865.56,  536.51] },  // DAEGU (bottom)
    12: { user: [554.20,  537.38], robot: [619.94,  537.78] },  // CHANCE (bottom)
    13: { user: [300.99,  537.38], robot: [366.72,  537.78] },  // BUNDANG (bottom)
  },
};

const BOARD_LAYOUTS = {
  "final": BOARD_FINAL_LAYOUT,
};

// ---- HTTP helpers ----------------------------------------------------------

async function fetchJson(path, init) {
  const r = await fetch(path, init);
  if (!r.ok) throw Object.assign(new Error(`${path} -> ${r.status}`),
                                 { status: r.status, body: await r.text() });
  return r.json();
}
async function postJson(path, body) {
  return fetchJson(path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

// ---- adapter badges -------------------------------------------------------

function modeBadge(label, health) {
  const mode = health.mode || (health.enabled ? "on" : "off");
  const cls = ["live", "on"].includes(mode) ? mode : "stub";
  return `<span class="badge ${cls}"><span class="dot"></span>${label}:${mode}</span>`;
}
async function loadBadges() {
  // Adapter modes are set at server startup (lifespan() from env) and
  // don't change during a session — fetch once at boot, no interval.
  try {
    const m = await fetchJson("/api/modes");
    document.getElementById("modes").innerHTML =
      modeBadge("STT", m.stt) + modeBadge("VLM", m.vlm) +
      modeBadge("Robot", m.robot) + modeBadge("ROS2", m.ros2);
  } catch (err) { console.warn("modes fetch failed:", err); }
}

// ---- board rendering ------------------------------------------------------

let boardTiles = null;

async function loadBoardVisual(boardId) {
  const host = document.getElementById("board-host");
  const pieces = document.getElementById("pieces");

  const layout = BOARD_LAYOUTS[boardId];
  pieces.setAttribute("viewBox", `0 0 ${layout.viewBox.w} ${layout.viewBox.h}`);

  const boardJson = await fetchJson(`/assets/boards/board_${boardId}.json`);
  boardTiles = boardJson.tiles;
  host.innerHTML = `<img src="/assets/boards/${boardJson.physical_image}" alt="Board ${boardId}"/>`;
}

function movePiece(player, tileIndex, boardId) {
  const layout = BOARD_LAYOUTS[boardId];
  const tile = layout?.centers?.[tileIndex];
  const coords = tile?.[player];
  if (!coords) return;
  const [cx, cy] = coords;
  const el = document.getElementById(`piece-${player}`);
  const half = parseFloat(el.getAttribute("width")) / 2;
  el.setAttribute("x", cx - half);
  el.setAttribute("y", cy - half);
  el.removeAttribute("transform");
  updatePieceReadout();
}

// ---- piece drag calibration ----------------------------------------------

let updatePieceReadout = () => {};

function setupPieceDragging() {
  const pieces = document.getElementById("pieces");
  const userRect = document.getElementById("piece-user");
  const robotRect = document.getElementById("piece-robot");
  const readout = document.getElementById("board-coords");
  if (!pieces || !userRect || !robotRect || !readout) return;

  const transformOffset = (rect) => {
    const tr = rect.getAttribute("transform");
    if (!tr) return [0, 0];
    const m = tr.match(/translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)/);
    return m ? [parseFloat(m[1]), parseFloat(m[2])] : [0, 0];
  };

  const visualCenter = (rect) => {
    const x = parseFloat(rect.getAttribute("x"));
    const y = parseFloat(rect.getAttribute("y"));
    const w = parseFloat(rect.getAttribute("width"));
    const h = parseFloat(rect.getAttribute("height"));
    const [tx, ty] = transformOffset(rect);
    return [x + w / 2 + tx, y + h / 2 + ty];
  };

  const fmt = (n) => n.toFixed(2);

  updatePieceReadout = () => {
    const [ux, uy] = visualCenter(userRect);
    const [rx, ry] = visualCenter(robotRect);
    readout.textContent =
      `user: (${fmt(ux)}, ${fmt(uy)})  |  robot: (${fmt(rx)}, ${fmt(ry)})`;
  };

  const svgPoint = (evt) => {
    const pt = pieces.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    return pt.matrixTransform(pieces.getScreenCTM().inverse());
  };

  let dragging = null;
  let dragOffset = { x: 0, y: 0 };

  for (const rect of [userRect, robotRect]) {
    rect.addEventListener("pointerdown", (evt) => {
      dragging = rect;
      rect.classList.add("dragging");
      const pt = svgPoint(evt);
      const [cx, cy] = visualCenter(rect);
      dragOffset.x = pt.x - cx;
      dragOffset.y = pt.y - cy;
      rect.setPointerCapture(evt.pointerId);
      evt.preventDefault();
    });
    rect.addEventListener("pointermove", (evt) => {
      if (dragging !== rect) return;
      const pt = svgPoint(evt);
      const newCx = pt.x - dragOffset.x;
      const newCy = pt.y - dragOffset.y;
      const w = parseFloat(rect.getAttribute("width"));
      const h = parseFloat(rect.getAttribute("height"));
      const [tx, ty] = transformOffset(rect);
      rect.setAttribute("x", newCx - w / 2 - tx);
      rect.setAttribute("y", newCy - h / 2 - ty);
      updatePieceReadout();
    });
    const stop = (evt) => {
      if (dragging !== rect) return;
      dragging = null;
      rect.classList.remove("dragging");
      try { rect.releasePointerCapture(evt.pointerId); } catch (_) {}
    };
    rect.addEventListener("pointerup", stop);
    rect.addEventListener("pointercancel", stop);
  }

  updatePieceReadout();
}

// ---- money widget ---------------------------------------------------------

const lastBalance = { user: null, robot: null };
function renderMoney(snap) {
  for (const p of ["user", "robot"]) {
    const el = document.getElementById(`money-${p}-value`);
    const prev = lastBalance[p];
    const curr = snap[p] ?? 0;
    el.textContent = `$${curr}`;
    if (prev !== null && curr !== prev) {
      el.classList.remove("flash-up", "flash-down");
      void el.offsetWidth; // reflow so animation replays
      el.classList.add(curr > prev ? "flash-up" : "flash-down");
      setTimeout(() => el.classList.remove("flash-up", "flash-down"), 600);
    }
    lastBalance[p] = curr;
  }
}

// ---- dice face ------------------------------------------------------------

// Pip positions on a 3×3 grid (row, col) for each die value.
const DICE_PIPS = {
  1: [[1, 1]],
  2: [[0, 0], [2, 2]],
  3: [[0, 0], [1, 1], [2, 2]],
  4: [[0, 0], [0, 2], [2, 0], [2, 2]],
  5: [[0, 0], [0, 2], [1, 1], [2, 0], [2, 2]],
  6: [[0, 0], [0, 2], [1, 0], [1, 2], [2, 0], [2, 2]],
};

function renderDiceFace(value) {
  const face = document.getElementById("dice-face");
  const pips = DICE_PIPS[value];
  if (!pips) {
    face.classList.add("empty");
    face.innerHTML = "";
    return;
  }
  face.classList.remove("empty");
  face.innerHTML = pips.map(([r, c]) =>
    `<span class="dice-pip" style="grid-row:${r + 1};grid-column:${c + 1}"></span>`
  ).join("");
}

// ---- decision modal -------------------------------------------------------

let pendingDecision = null;  // { property_id, card }

function showDecision(decision) {
  pendingDecision = decision;
  const { card } = decision;
  const host = document.getElementById("decision-card");
  host.innerHTML = `
    <div class="card-preview">
      <div class="kind">${card.kind}</div>
      <div class="name">${card.name}</div>
      <div class="price">Price $${card.price_buy}${card.price_building ? ` · build $${card.price_building}` : ''}</div>
    </div>
  `;
  document.getElementById("decision-title").textContent = `Land on ${card.name}`;
  const canBuild = card.kind === "property" && card.price_building !== null;
  document.getElementById("btn-buy-build").style.display = canBuild ? "inline-block" : "none";
  document.getElementById("decision-modal").classList.remove("hidden");
}

function hideDecision() {
  pendingDecision = null;
  document.getElementById("decision-modal").classList.add("hidden");
}

async function submitDecision(action, houseCount = 0) {
  if (!pendingDecision) return;
  const pid = pendingDecision.property_id;
  try {
    await postJson(`/api/properties/${encodeURIComponent(pid)}/decide`,
                   { action, house_count: houseCount });
  } catch (err) { console.warn("decide:", err); }
  hideDecision();
}

// ---- announcement (human-readable banner below the board) -----------------

let lastAnnouncedTurn = null;

function tileName(idx) {
  if (idx === null || idx === undefined) return "—";
  return boardTiles?.[idx]?.name ?? `tile ${idx}`;
}

function propertyName(pid) {
  if (!pid) return "a property";
  const prop = currentState?.properties?.[pid];
  if (prop && typeof prop.tile_index === "number") return tileName(prop.tile_index);
  // property_id is usually `${board_id}:${tile_name_slug}` — fall back to the suffix.
  const idx = String(pid).lastIndexOf(":");
  return idx >= 0 ? String(pid).slice(idx + 1).replace(/_/g, " ") : pid;
}

function announce(text, kind = "info") {
  const el = document.getElementById("notification");
  if (!el) return;
  el.classList.remove("empty");
  el.className = `notification kind-${kind}`;
  el.textContent = text;
}

function announceFromEvent(env) {
  const { type, payload = {} } = env;
  switch (type) {
    case "game_started":
      announce("Game started", "turn");
      lastAnnouncedTurn = null;
      break;
    case "dice_submitted": {
      const player = currentState?.turn ?? "player";
      const sum = payload.sum ?? payload.value;
      announce(`${player} rolled ${sum}`, "dice");
      break;
    }
    case "move_applied":
      announce(`${payload.player} moved to ${tileName(payload.to_tile)}`, "move");
      break;
    case "lap_completed":
      announce(`${payload.player} passed GO`, "move");
      break;
    case "start_bonus":
      announce(`${payload.player} collected $${payload.amount} for passing GO`, "money");
      break;
    case "property_bought":
      announce(`${payload.owner} bought ${propertyName(payload.property_id)} for $${payload.price}`, "buy");
      break;
    case "purchase_skipped":
      announce(`Purchase skipped`, "buy");
      break;
    case "property_built":
      announce(`Built on ${propertyName(payload.property_id)}`, "build");
      break;
    case "property_mortgaged":
      announce(`Mortgaged ${propertyName(payload.property_id)}`, "money");
      break;
    case "property_unmortgaged":
      announce(`Unmortgaged ${propertyName(payload.property_id)}`, "money");
      break;
    case "building_sold":
      announce(`Sold building on ${propertyName(payload.property_id)}`, "money");
      break;
    case "tile_rent_paid":
      announce(`Rent paid${payload.amount ? ` ($${payload.amount})` : ""}`, "money");
      break;
    case "tile_tax_paid":
      announce(`Tax paid${payload.amount ? ` ($${payload.amount})` : ""}`, "money");
      break;
    case "game_won":
      announce(`🏆 ${payload.winner} wins the game!`, "win");
      break;
    case "state_loaded":
      announce("Game state loaded", "turn");
      lastAnnouncedTurn = null;
      break;
  }
}

// ---- event log ------------------------------------------------------------

function logEvent(env) {
  const ol = document.getElementById("event-log");
  const li = document.createElement("li");
  li.className = `type-${env.type}`;
  const ts = env.ts ? env.ts.slice(11, 19) : "";
  li.innerHTML = `<span class="ts">${ts}</span>${env.type} ${JSON.stringify(env.payload)}`;
  ol.prepend(li);
  while (ol.children.length > 80) ol.removeChild(ol.lastChild);
}

// ---- is_YOLO toggle -------------------------------------------------------

// is_YOLO lives in server RuntimeConfig so SAVE/LOAD STATE persists it.
// Mirror it locally so the Toggle button can flip without a round trip.
let isYOLO = true;

function renderYoloStatus() {
  const el = document.getElementById("st-is-yolo");
  if (el) el.textContent = isYOLO ? "ON" : "OFF";
}

// ---- state reconciliation -------------------------------------------------

let currentState = null;

function renderState(state) {
  if (state.config && typeof state.config.is_YOLO === "boolean") {
    isYOLO = state.config.is_YOLO;
    renderYoloStatus();
  }
  document.getElementById("st-turn").textContent = state.turn;
  // Single-die manual input stores as (value, 0); only render the "+ d2"
  // part when we actually rolled two dice (doubles detection).
  const ld = state.last_dice;
  document.getElementById("st-dice").textContent = !ld
    ? "—"
    : ld[1] > 0
      ? `${ld[0]} + ${ld[1]} = ${state.last_dice_sum}`
      : String(ld[0]);
  renderDiceFace(ld ? ld[0] : null);

  for (const p of ["user", "robot"]) {
    const pos = state.positions[p];
    const tileName = boardTiles?.[pos]?.name;
    document.getElementById(`st-pos-${p}`).textContent =
      pos === undefined ? "—" : (tileName ?? pos);
    if (pos !== undefined) movePiece(p, pos, state.board_id);
  }
  const money = {};
  for (const [pid, ps] of Object.entries(state.players || {})) money[pid] = ps.balance;
  renderMoney(money);

  const winner = state.winner;
  document.getElementById("btn-apply-move").disabled = state.fsm !== "MOVING";
  document.getElementById("btn-roll-dice").disabled = state.fsm !== "TURN_START";
  document.getElementById("btn-end-turn").disabled =
    !["RESOLVE_TILE", "END_TURN"].includes(state.fsm) || winner;

  // Whose turn is it? — announce when it flips. Skip if a winner has been
  // declared so the "X wins" banner isn't overwritten by a stale turn label.
  if (!winner && state.turn && state.turn !== lastAnnouncedTurn) {
    lastAnnouncedTurn = state.turn;
    announce(`It's ${state.turn}'s turn`, "turn");
  }
}

async function refreshState() {
  currentState = await fetchJson("/api/game/state");
  renderState(currentState);
}

// ---- WebSocket stream ----------------------------------------------------

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
    if (env.type === "tile_property_arrival_buyable" && env.payload.needs_decision) {
      showDecision({
        property_id: env.payload.property_id,
        card: env.payload.card,
      });
    }
    announceFromEvent(env);
    await refreshState();
  };
  ws.onclose = () => setTimeout(openStream, 1500);
  ws.onerror = () => ws.close();
}

// ---- manual controls ------------------------------------------------------

document.getElementById("btn-roll-dice").addEventListener("click", async () => {
  // The robot runs pick_and_place.py dice GO; after pnp.get_piece_info() the
  // server reads the face value from /yolo_dice_detector/dice_number and
  // submits it as the dice roll. Disable the button while we wait.
  const btn = document.getElementById("btn-roll-dice");
  const prevText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Rolling…";
  let rolled = false;
  try {
    const result = await postJson("/api/dice/roll_robot", { is_YOLO: isYOLO });
    if (result && typeof result.dice_number === "number") {
      renderDiceFace(result.dice_number);
      rolled = true;
    }
  } catch (err) {
    console.warn("roll_robot:", err);
  } finally {
    btn.textContent = prevText;
    // On success the WS fsm_transition event will set disabled correctly via
    // renderState. On failure no event fires, so re-enable here so the user
    // can retry.
    if (!rolled) btn.disabled = false;
  }
});
document.getElementById("btn-apply-move").addEventListener("click", async () => {
  if (!currentState || !currentState.last_dice_sum) return;
  const player = currentState.turn;
  const from = currentState.positions[player];
  const size = BOARD_LAYOUTS[currentState.board_id]
    ? Object.keys(BOARD_LAYOUTS[currentState.board_id].centers).length
    : 40;
  const to = (from + currentState.last_dice_sum) % size;
  // /api/move/apply_robot runs pick_and_place.py (red_cube for user,
  // green_cube for robot) and only applies the game-state move once the
  // physical motion finishes — so the on-screen piece moves at the same
  // moment the robot arrives at the new tile.
  const btn = document.getElementById("btn-apply-move");
  const prevText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Moving…";
  let moved = false;
  try {
    await postJson("/api/move/apply_robot", {
      player, from_tile: from, to_tile: to, is_YOLO: isYOLO,
    });
    moved = true;
  } catch (err) {
    console.warn("apply_move:", err);
  } finally {
    btn.textContent = prevText;
    // On success the WS fsm_transition event drives renderState which sets
    // disabled correctly. On failure no event fires, so re-enable here.
    if (!moved) btn.disabled = false;
  }
});
document.getElementById("btn-end-turn").addEventListener("click", async () => {
  await postJson("/api/game/end_turn");
});
document.getElementById("btn-reset").addEventListener("click", async () => {
  await postJson("/api/game/start", { board: "final" });
  await loadBoardVisual("final");
  await refreshState();
});
document.getElementById("btn-toggle-yolo").addEventListener("click", async () => {
  const next = !isYOLO;
  try {
    const cfg = await postJson("/api/game/config", { is_YOLO: next });
    isYOLO = !!cfg.is_YOLO;
  } catch (err) {
    console.warn("toggle is_YOLO:", err);
    isYOLO = next;  // local fallback so the UI still reflects the click
  }
  renderYoloStatus();
});
document.getElementById("btn-save-state").addEventListener("click", async () => {
  const btn = document.getElementById("btn-save-state");
  const prevText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    await postJson("/api/game/save_state");
  } catch (err) {
    console.warn("save_state:", err);
    alert(`Save failed: ${err.message || err}`);
  } finally {
    btn.textContent = prevText;
    btn.disabled = false;
  }
});
document.getElementById("btn-load-state").addEventListener("click", async () => {
  const btn = document.getElementById("btn-load-state");
  const prevText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Loading…";
  try {
    await postJson("/api/game/load_state");
    await refreshState();
  } catch (err) {
    console.warn("load_state:", err);
    alert(`Load failed: ${err.message || err}`);
  } finally {
    btn.textContent = prevText;
    btn.disabled = false;
  }
});
document.getElementById("btn-skip").addEventListener("click", () => submitDecision("skip"));
document.getElementById("btn-buy").addEventListener("click", () => submitDecision("buy"));
document.getElementById("btn-buy-build").addEventListener("click", () => submitDecision("build", 1));

// ---- VLM ask --------------------------------------------------------------

const VLM_HOST = `${location.hostname}:8000`;
const VLM_BASE = `${location.protocol}//${VLM_HOST}`;

function setupVlm() {
  const prompt   = document.getElementById("vlm-prompt");
  const askBtn   = document.getElementById("vlm-ask");
  const repeat   = document.getElementById("vlm-repeat");
  const interval = document.getElementById("vlm-interval");
  const respEl   = document.getElementById("vlm-response");
  const metaEl   = document.getElementById("vlm-meta");
  const loopDot  = document.getElementById("vlm-loop-dot");
  const loopLbl  = document.getElementById("vlm-loop-status");

  let loopTimer = null;
  let inFlight  = false;

  async function askOnce() {
    if (inFlight) return;
    inFlight = true;
    askBtn.disabled = true;
    askBtn.textContent = "Thinking…";
    respEl.className = "vlm-response empty";
    respEl.textContent = "Waiting for VLM response…";
    const started = performance.now();
    try {
      const r = await fetch(`${VLM_BASE}/api/vlm/infer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera: "none", prompt: prompt.value.trim() || null, client: "robopoly" }),
      });
      const body = await r.json();
      const elapsedMs = Math.round(performance.now() - started);
      if (!r.ok) {
        respEl.className = "vlm-response error";
        respEl.textContent = body.detail || `HTTP ${r.status}`;
        metaEl.textContent = `${elapsedMs} ms`;
        return;
      }
      respEl.className = "vlm-response";
      respEl.textContent = body.response || "(empty response)";
      const ts = new Date().toLocaleTimeString();
      metaEl.textContent = `${elapsedMs} ms · ${ts}`;
    } catch (err) {
      respEl.className = "vlm-response error";
      respEl.textContent = String(err);
    } finally {
      inFlight = false;
      askBtn.disabled = false;
      askBtn.textContent = "Ask";
    }
  }

  function scheduleNext() {
    if (!repeat.checked) return;
    const delayMs = Number(interval.value) * 1000;
    loopTimer = setTimeout(async () => {
      if (!repeat.checked) return;
      await askOnce();
      scheduleNext();
    }, delayMs);
  }
  function stopLoop() {
    if (loopTimer !== null) { clearTimeout(loopTimer); loopTimer = null; }
    loopDot.classList.remove("live");
    loopLbl.textContent = "idle";
  }
  function startLoop() {
    stopLoop();
    loopDot.classList.add("live");
    loopLbl.textContent = `every ${interval.value}s`;
    askOnce().then(scheduleNext);
  }

  askBtn.addEventListener("click", () => {
    if (repeat.checked) startLoop(); else askOnce();
  });
  prompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (repeat.checked) startLoop(); else askOnce();
    }
  });
  repeat.addEventListener("change", () => {
    if (repeat.checked) startLoop(); else stopLoop();
  });
  interval.addEventListener("change", () => {
    if (repeat.checked) {
      loopLbl.textContent = `every ${interval.value}s`;
      if (loopTimer !== null) { clearTimeout(loopTimer); loopTimer = null; }
      if (!inFlight) scheduleNext();
    }
  });

  // System prompt
  const sp       = document.getElementById("vlm-system-prompt");
  const spSave   = document.getElementById("vlm-sp-save");
  const spReset  = document.getElementById("vlm-sp-reset");
  const spStatus = document.getElementById("vlm-sp-status");
  let spServer = "";

  function setSpStatus(text, isError = false) {
    spStatus.textContent = text;
    spStatus.style.color = isError ? "#fca5a5" : "#64748b";
  }
  function updateDirty() {
    const dirty = sp.value !== spServer;
    spSave.disabled = !dirty;
    if (dirty) setSpStatus("unsaved changes");
  }
  async function loadSp() {
    try {
      const r = await fetch(`${VLM_BASE}/api/vlm/system_prompt?client=robopoly`);
      const body = await r.json();
      spServer = body.system_prompt || "";
      sp.value = spServer;
      setSpStatus("loaded");
      spSave.disabled = true;
    } catch (err) { setSpStatus(`load failed: ${err}`, true); }
  }
  async function saveSp() {
    spSave.disabled = true;
    setSpStatus("saving…");
    try {
      const r = await fetch(`${VLM_BASE}/api/vlm/system_prompt?client=robopoly`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_prompt: sp.value }),
      });
      const body = await r.json();
      if (!r.ok) { setSpStatus(body.detail || `HTTP ${r.status}`, true); return; }
      spServer = body.system_prompt;
      sp.value = spServer;
      setSpStatus("saved");
    } catch (err) { setSpStatus(`save failed: ${err}`, true); }
    finally { updateDirty(); }
  }
  async function resetSp() {
    if (!confirm("Reset system prompt to default?")) return;
    setSpStatus("resetting…");
    try {
      const r = await fetch(`${VLM_BASE}/api/vlm/system_prompt?client=robopoly`, { method: "DELETE" });
      const body = await r.json();
      if (!r.ok) { setSpStatus(body.detail || `HTTP ${r.status}`, true); return; }
      spServer = body.system_prompt;
      sp.value = spServer;
      setSpStatus("reset to default");
      spSave.disabled = true;
    } catch (err) { setSpStatus(`reset failed: ${err}`, true); }
  }
  sp.addEventListener("input", updateDirty);
  spSave.addEventListener("click", saveSp);
  spReset.addEventListener("click", resetSp);
  loadSp();

  // Speech-to-text — routed through the orchestrator's /api/whisper/transcribe.
  const mic       = document.getElementById("vlm-mic");
  const micDevice = document.getElementById("vlm-mic-device");
  const sttStatus = document.getElementById("vlm-stt-status");

  let sttRecorder = null;
  let sttChunks   = [];
  let sttStream   = null;

  function setSttStatus(text, isError = false) {
    sttStatus.textContent = text;
    sttStatus.style.color = isError ? "#fca5a5" : "#64748b";
  }
  function stopSttTracks() {
    if (sttStream) {
      sttStream.getTracks().forEach(t => t.stop());
      sttStream = null;
    }
  }
  async function populateMicDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter((d) => d.kind === "audioinput");
      const previous = micDevice.value;
      micDevice.innerHTML = '<option value="">Default microphone</option>';
      audioInputs.forEach((d, i) => {
        const opt = document.createElement("option");
        opt.value = d.deviceId;
        opt.textContent = d.label || `Microphone ${i + 1}`;
        micDevice.appendChild(opt);
      });
      if (previous && [...micDevice.options].some((o) => o.value === previous)) {
        micDevice.value = previous;
      }
    } catch (err) {
      console.warn("enumerateDevices failed:", err);
    }
  }
  populateMicDevices();
  navigator.mediaDevices?.addEventListener?.("devicechange", populateMicDevices);

  async function transcribeBlob(blob) {
    const form = new FormData();
    const ext = (blob.type.includes("webm") ? "webm"
               : blob.type.includes("ogg")  ? "ogg"
               : blob.type.includes("mp4")  ? "mp4"
               : "wav");
    form.append("file", blob, `mic.${ext}`);

    setSttStatus("transcribing…");
    const started = performance.now();
    try {
      const r = await fetch(`${VLM_BASE}/api/whisper/transcribe`, { method: "POST", body: form });
      const elapsedMs = Math.round(performance.now() - started);
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try { const j = await r.json(); if (j.detail) detail = j.detail; } catch {}
        setSttStatus(`${detail} (${elapsedMs} ms)`, true);
        return;
      }
      const body = await r.json();
      if (body.error) { setSttStatus(`failed: ${body.error}`, true); return; }
      const text = (body.text || "").trim();
      if (text) {
        prompt.value = prompt.value
          ? `${prompt.value.trimEnd()} ${text}`
          : text;
        prompt.focus();
      }
      setSttStatus(text ? `transcribed (${elapsedMs} ms)` : `empty result (${elapsedMs} ms)`);
    } catch (err) {
      setSttStatus(`failed: ${err}`, true);
    }
  }
  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setSttStatus("mic not available in this browser", true);
      return;
    }
    try {
      const deviceId = micDevice.value;
      const constraints = { audio: deviceId ? { deviceId: { exact: deviceId } } : true };
      sttStream = await navigator.mediaDevices.getUserMedia(constraints);
      // Labels are only revealed after permission is granted — repopulate.
      populateMicDevices();
    } catch (err) {
      setSttStatus(`mic denied: ${err.name || err}`, true);
      return;
    }
    sttChunks = [];
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : (MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "");
    sttRecorder = mime ? new MediaRecorder(sttStream, { mimeType: mime })
                       : new MediaRecorder(sttStream);
    sttRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) sttChunks.push(e.data); };
    sttRecorder.onstop = async () => {
      stopSttTracks();
      mic.classList.remove("recording");
      mic.textContent = "Rec";
      mic.title = "Record voice and transcribe via Whisper";
      if (sttChunks.length === 0) { setSttStatus("no audio captured", true); return; }
      const blob = new Blob(sttChunks, { type: sttRecorder.mimeType || "audio/webm" });
      sttChunks = [];
      await transcribeBlob(blob);
    };
    sttRecorder.start();
    mic.classList.add("recording");
    mic.textContent = "Stop";
    mic.title = "Stop recording";
    setSttStatus("recording…");
  }
  function stopRecording() {
    if (sttRecorder && sttRecorder.state !== "inactive") {
      sttRecorder.stop();
    } else {
      stopSttTracks();
    }
  }
  mic.addEventListener("click", () => {
    if (sttRecorder && sttRecorder.state === "recording") stopRecording();
    else startRecording();
  });

  // VLM memory (vector DB) — talks to the orchestrator at VLM_BASE.
  const memStatus = document.getElementById("vlm-mem-status");
  const memClear  = document.getElementById("vlm-mem-clear");

  async function refreshMemoryStatus() {
    try {
      const r = await fetch(`${VLM_BASE}/api/vlm/memory`);
      const body = await r.json();
      if (!r.ok) { memStatus.textContent = "memory: error"; return; }
      const tag = body.enabled ? "" : " (disabled)";
      memStatus.textContent = body.count === null
        ? `memory: unreachable${tag}`
        : `memory: ${body.count} stored${tag}`;
    } catch {
      memStatus.textContent = "memory: unreachable";
    }
  }
  async function clearMemory() {
    if (!confirm("Delete all stored memories from the vector DB? This cannot be undone.")) return;
    memClear.disabled = true;
    const prev = memClear.textContent;
    memClear.textContent = "Clearing…";
    try {
      const r = await fetch(`${VLM_BASE}/api/vlm/memory`, { method: "DELETE" });
      const body = await r.json();
      if (!r.ok || !body.ok) alert(`Clear failed: ${body.error || r.status}`);
    } catch (err) {
      alert(`Clear failed: ${err}`);
    } finally {
      memClear.disabled = false;
      memClear.textContent = prev;
      refreshMemoryStatus();
    }
  }
  memClear.addEventListener("click", clearMemory);
  refreshMemoryStatus();
  setInterval(refreshMemoryStatus, 5000);

  // Refresh memory counter right after every inference.
  const _askOnceOrig = askOnce;
  askOnce = async function() {
    await _askOnceOrig();
    refreshMemoryStatus();
  };
}

// ---- boot -----------------------------------------------------------------

(async () => {
  await loadBadges();
  await loadBoardVisual("final");
  setupPieceDragging();
  renderYoloStatus();
  await refreshState();
  openStream();
  setupVlm();
})();
