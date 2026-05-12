/**
 * movensys-monopoly UI.
 *
 * Single board: 16-tile JSON model rendered on a 14-cell rectangular
 * perimeter (5 wide × 4 tall grid). Indexing is counter-clockwise from
 * GO at the bottom-left corner.
 * The viewBox matches board.png (1261×584 ≈ 2.16:1).
 *
 * NOTE: the new board.png omits two cells the JSON still defines —
 * INCHEON AIRPORT (3) and GANGNEUNG (11) — so those pieces visually
 * collapse onto the adjacent corner. The right column also shows
 * GYEONGJU above BUSAN, opposite of the old image; coords below
 * follow the image labels so pieces land on the correctly-named cell.
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
    3:  { user: [52.20,   170.85], robot: [119.20,  170.62] },  // INCHEON AIRPORT (no visible cell — placed between SEOUL and IN JAIL)
    4:  { user: [52.83,   99.32],  robot: [118.57,  98.45]  },  // IN JAIL (TL)
    5:  { user: [298.45,  106.91], robot: [365.45,  106.05] },  // ELECTRIC COMPANY (top)
    6:  { user: [546.61,  105.65], robot: [611.07,  104.78] },  // JEONJU (top)
    7:  { user: [803.62,  105.65], robot: [870.62,  104.78] },  // DAEJEON (top)
    8:  { user: [1049.24, 108.18], robot: [1114.97, 107.31] },  // NON-FREE PARKING (TR)
    9:  { user: [1051.77, 385.45], robot: [1114.97, 384.58] },  // BUSAN (right, lower mid — per image)
    10: { user: [1050.51, 243.65], robot: [1114.97, 244.05] },  // GYEONGJU (right, upper mid — per image)
    11: { user: [1051.77, 460.78], robot: [1116.24, 460.55] },  // GANGNEUNG (no visible cell — placed between BUSAN and GO TO JAIL)
    12: { user: [1051.77, 536.11], robot: [1117.51, 536.51] },  // GO TO JAIL (BR)
    13: { user: [801.09,  536.11], robot: [865.56,  536.51] },  // DAEGU (bottom)
    14: { user: [554.20,  537.38], robot: [619.94,  537.78] },  // CHANCE (bottom)
    15: { user: [300.99,  537.38], robot: [366.72,  537.78] },  // BUNDANG (bottom)
  },
};

const BOARD_LAYOUTS = {
  "final": BOARD_FINAL_LAYOUT,
};

const COLOR_HEX = {
  brown: "#8B4513", light_blue: "#87CEEB", pink: "#E91E63",
  orange: "#FF9800", red: "#D32F2F", yellow: "#FDD835",
  green: "#388E3C", dark_blue: "#1A237E",
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
      modeBadge("STT", m.stt) + modeBadge("LLM", m.llm) +
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

// ---- property sidebar -----------------------------------------------------

function groupByColor(properties) {
  const groups = {};
  for (const p of properties) {
    const key = p.color_group || p.kind;
    (groups[key] ??= []).push(p);
  }
  return groups;
}

function renderPropertyLists(properties) {
  for (const player of ["user", "robot"]) {
    const host = document.getElementById(`props-${player}`);
    const mine = properties.filter(p => p.owner === player);
    if (mine.length === 0) {
      host.innerHTML = `<p class="muted" style="font-size:11px;color:var(--muted);margin:0">none yet</p>`;
      continue;
    }
    const groups = groupByColor(mine);
    const frags = [];
    for (const [name, items] of Object.entries(groups)) {
      frags.push(`<div class="property-group"><div class="property-group-name">${name}</div>`);
      for (const p of items) {
        const swatch = COLOR_HEX[p.color_group] || "#888";
        const buildings = p.has_hotel ? "🏨" : "🏠".repeat(p.houses);
        const cls = ["property-thumb"];
        if (p.mortgaged) cls.push("mortgaged");
        frags.push(
          `<div class="${cls.join(" ")}" title="${p.name}">` +
          `<span class="swatch" style="background:${swatch}"></span>` +
          `<span class="name">${p.name}</span>` +
          `<span class="buildings">${buildings}</span></div>`
        );
      }
      frags.push(`</div>`);
    }
    host.innerHTML = frags.join("");
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
  const swatch = COLOR_HEX[card.color_group] || "#888";
  host.innerHTML = `
    <div class="card-preview" style="background:${swatch}; color:#fff; text-shadow:0 1px 1px rgba(0,0,0,.4)">
      <div class="kind">${card.kind}${card.color_group ? ' · ' + card.color_group : ''}</div>
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

// ---- state reconciliation -------------------------------------------------

let currentState = null;

function renderState(state) {
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
}

async function refreshState() {
  currentState = await fetchJson("/api/game/state");
  renderState(currentState);
  try {
    const props = await fetchJson("/api/properties");
    renderPropertyLists(props);
  } catch (err) { /* properties empty before start */ }
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
    await refreshState();
  };
  ws.onclose = () => setTimeout(openStream, 1500);
  ws.onerror = () => ws.close();
}

// ---- manual controls ------------------------------------------------------

document.getElementById("btn-roll-dice").addEventListener("click", async () => {
  const value = 1 + Math.floor(Math.random() * 6);
  renderDiceFace(value);
  await postJson("/api/dice/submit", { value, source: "manual" });
});
document.getElementById("btn-apply-move").addEventListener("click", async () => {
  if (!currentState || !currentState.last_dice_sum) return;
  const player = currentState.turn;
  const from = currentState.positions[player];
  const size = BOARD_LAYOUTS[currentState.board_id]
    ? Object.keys(BOARD_LAYOUTS[currentState.board_id].centers).length
    : 40;
  const to = (from + currentState.last_dice_sum) % size;
  try { await postJson("/api/move/apply", { player, from_tile: from, to_tile: to }); }
  catch (err) { console.warn("apply_move:", err); }
});
document.getElementById("btn-end-turn").addEventListener("click", async () => {
  await postJson("/api/game/end_turn");
});
document.getElementById("btn-reset").addEventListener("click", async () => {
  await postJson("/api/game/start", { board: "final" });
  await loadBoardVisual("final");
  await refreshState();
});
document.getElementById("btn-skip").addEventListener("click", () => submitDecision("skip"));
document.getElementById("btn-buy").addEventListener("click", () => submitDecision("buy"));
document.getElementById("btn-buy-build").addEventListener("click", () => submitDecision("build", 1));

// ---- camera thumbs --------------------------------------------------------

const VLM_HOST = `${location.hostname}:8000`;

function openCameraFeed(path, imgId, statusId, cellId, dotId) {
  const img = document.getElementById(imgId);
  const status = document.getElementById(statusId);
  const cell = document.getElementById(cellId);
  const dot = dotId ? document.getElementById(dotId) : null;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${VLM_HOST}${path}`);
  ws.onmessage = (ev) => {
    const payload = JSON.parse(ev.data);
    if (payload.error || !payload.data?.data) {
      cell.classList.remove("live");
      if (dot) dot.classList.remove("live");
      status.textContent = "No stream";
      return;
    }
    cell.classList.add("live");
    if (dot) dot.classList.add("live");
    img.src = `data:image/jpeg;base64,${payload.data.data}`;
    const enc = payload.data.encoding ? ` · ${payload.data.encoding}` : "";
    status.textContent = `${payload.data.width}×${payload.data.height}${enc}`;
  };
  ws.onerror = () => {
    cell.classList.remove("live");
    if (dot) dot.classList.remove("live");
  };
  ws.onclose = () => {
    cell.classList.remove("live");
    if (dot) dot.classList.remove("live");
    status.textContent = "No stream";
    setTimeout(() => openCameraFeed(path, imgId, statusId, cellId, dotId), 3000);
  };
}

// ---- VLM ask --------------------------------------------------------------

const VLM_BASE = `${location.protocol}//${VLM_HOST}`;

function setupVlm() {
  const camera   = document.getElementById("vlm-camera");
  const prompt   = document.getElementById("vlm-prompt");
  const askBtn   = document.getElementById("vlm-ask");
  const repeat   = document.getElementById("vlm-repeat");
  const interval = document.getElementById("vlm-interval");
  const respEl   = document.getElementById("vlm-response");
  const metaEl   = document.getElementById("vlm-meta");
  const loopDot  = document.getElementById("vlm-loop-dot");
  const loopLbl  = document.getElementById("vlm-loop-status");
  const sentImg  = document.getElementById("vlm-sent-image");
  const imgPh    = document.getElementById("vlm-img-placeholder");
  const imgMeta  = document.getElementById("vlm-img-meta");
  const rotate   = document.getElementById("vlm-rotate180");

  let loopTimer = null;
  let inFlight  = false;

  sentImg.addEventListener("error", () => {
    sentImg.classList.remove("has-image");
    imgPh.classList.remove("hidden");
    imgPh.textContent = "Failed to render captured image.";
  });

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
        body: JSON.stringify({ camera: camera.value, prompt: prompt.value.trim() || null, rotate180: rotate.checked }),
      });
      const body = await r.json();
      const elapsedMs = Math.round(performance.now() - started);
      if (!r.ok) {
        respEl.className = "vlm-response error";
        respEl.textContent = body.detail || `HTTP ${r.status}`;
        metaEl.textContent = `camera=${camera.value} · ${elapsedMs} ms`;
        return;
      }
      respEl.className = "vlm-response";
      respEl.textContent = body.response || "(empty response)";
      const wh = (body.width && body.height) ? `${body.width}×${body.height}` : "—";
      const ts = new Date().toLocaleTimeString();
      metaEl.textContent = `camera=${body.camera} · frame=${wh} · ${elapsedMs} ms · ${ts}`;
      if (body.image) {
        sentImg.src = `data:image/jpeg;base64,${body.image}`;
        sentImg.classList.add("has-image");
        imgPh.classList.add("hidden");
        imgMeta.textContent = `${wh} · ${ts}`;
      }
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
      const r = await fetch(`${VLM_BASE}/api/vlm/system_prompt`);
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
      const r = await fetch(`${VLM_BASE}/api/vlm/system_prompt`, {
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
      const r = await fetch(`${VLM_BASE}/api/vlm/system_prompt`, { method: "DELETE" });
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

  // Speech-to-text via OpenAI-compatible Whisper server
  const mic       = document.getElementById("vlm-mic");
  const sttUrl    = document.getElementById("vlm-stt-url");
  const sttStatus = document.getElementById("vlm-stt-status");

  const STT_URL_KEY = "vlm-stt-url";
  const savedSttUrl = localStorage.getItem(STT_URL_KEY);
  if (savedSttUrl) sttUrl.value = savedSttUrl;
  sttUrl.addEventListener("change", () => {
    localStorage.setItem(STT_URL_KEY, sttUrl.value.trim());
  });

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
  async function transcribeBlob(blob) {
    const base = sttUrl.value.trim().replace(/\/+$/, "");
    if (!base) { setSttStatus("Whisper URL is empty", true); return; }
    const url = `${base}/v1/audio/transcriptions`;
    const form = new FormData();
    const ext = (blob.type.includes("webm") ? "webm"
               : blob.type.includes("ogg")  ? "ogg"
               : blob.type.includes("mp4")  ? "mp4"
               : "wav");
    form.append("file", blob, `speech.${ext}`);
    form.append("model", "whisper");
    form.append("response_format", "json");

    setSttStatus("transcribing…");
    const started = performance.now();
    try {
      const r = await fetch(url, { method: "POST", body: form });
      const elapsedMs = Math.round(performance.now() - started);
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try { const j = await r.json(); if (j.detail) detail = j.detail; } catch {}
        setSttStatus(`${detail} (${elapsedMs} ms)`, true);
        return;
      }
      const body = await r.json();
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
      sttStream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
      mic.textContent = "🎤";
      mic.title = "Record speech and transcribe via Whisper";
      if (sttChunks.length === 0) { setSttStatus("no audio captured", true); return; }
      const blob = new Blob(sttChunks, { type: sttRecorder.mimeType || "audio/webm" });
      sttChunks = [];
      await transcribeBlob(blob);
    };
    sttRecorder.start();
    mic.classList.add("recording");
    mic.textContent = "⏹";
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
}

// ---- boot -----------------------------------------------------------------

(async () => {
  await loadBadges();
  await loadBoardVisual("final");
  setupPieceDragging();
  await refreshState();
  openStream();
  openCameraFeed("/api/stream/image_top/rgb",   "feed-top-rgb",   "feed-top-rgb-status",   "feed-cell-top-rgb",   "feed-dot-top");
  openCameraFeed("/api/stream/image_hand/rgb",  "feed-hand-rgb",  "feed-hand-rgb-status",  "feed-cell-hand-rgb",  "feed-dot-hand");
  setupVlm();
})();
