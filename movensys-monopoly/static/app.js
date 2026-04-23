/**
 * movensys-monopoly UI.
 *
 * Boards 1 and 2 share a square perimeter layout — 4 corners plus
 * (tile_count - 4) / 4 tiles per side. Board 3 uses its specific 3x5
 * rectangle. Piece positions are computed on demand so the same code
 * handles all three.
 */

const BOARD3_LAYOUT = {
  viewBox: { w: 300, h: 500 },
  centers: {
    0: [250, 450], 1: [150, 450], 2: [50, 450],
    3: [50, 350], 4: [50, 250], 5: [50, 150],
    6: [50, 50], 7: [150, 50], 8: [250, 50],
    9: [250, 150], 10: [250, 250], 11: [250, 350],
  },
};

/** Compute tile-center pixel coordinates for a square-perimeter board.
 * `n` is total tiles; corners occupy `cornerRatio` × side-tile width
 * (Hasbro boards use ~1.5). Indexing is counter-clockwise from the
 * bottom-right GO corner.
 *
 * Board edge length = 2 * cornerWidth + perSide * sideTileWidth
 *                   = size
 * so sideTileWidth = size / (perSide + 2 * cornerRatio)
 */
function squarePerimeterCenters(n, size = 1000, cornerRatio = 1.5) {
  const perSide = (n - 4) / 4;
  const sideW = size / (perSide + 2 * cornerRatio);   // non-corner tile width
  const cornerW = cornerRatio * sideW;
  const halfCorner = cornerW / 2;
  const centers = {};

  // side-tile center along the axis of travel (from the corner edge, moving away)
  const sideCenter = (i) => cornerW + (i - 0.5) * sideW;  // i = 1..perSide

  centers[0] = [size - halfCorner, size - halfCorner];  // GO
  for (let i = 1; i <= perSide; i++) {
    // bottom row — moving left from GO: x decreases
    centers[i] = [size - sideCenter(i), size - halfCorner];
  }
  centers[perSide + 1] = [halfCorner, size - halfCorner];  // Jail / Just Visiting

  for (let i = 1; i <= perSide; i++) {
    // left column — moving up from Jail: y decreases
    centers[perSide + 1 + i] = [halfCorner, size - sideCenter(i)];
  }
  centers[2 * (perSide + 1)] = [halfCorner, halfCorner];  // Free Parking

  for (let i = 1; i <= perSide; i++) {
    // top row — moving right from Free Parking: x increases
    centers[2 * (perSide + 1) + i] = [sideCenter(i), halfCorner];
  }
  centers[3 * (perSide + 1)] = [size - halfCorner, halfCorner];  // Go To Jail

  for (let i = 1; i <= perSide; i++) {
    // right column — moving down from Go To Jail: y increases
    centers[3 * (perSide + 1) + i] = [size - halfCorner, sideCenter(i)];
  }
  return { viewBox: { w: size, h: size }, centers, cornerW, sideW };
}

const BOARD_LAYOUTS = {
  "1": squarePerimeterCenters(16, 1000, 1.5),
  "2": squarePerimeterCenters(40, 1000, 1.5),
  "3": BOARD3_LAYOUT,
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
  } catch (err) { console.warn("badge refresh failed:", err); }
}

// ---- board rendering ------------------------------------------------------

async function loadBoardVisual(boardId) {
  const wrap = document.getElementById("board-wrap");
  const host = document.getElementById("board-host");
  const pieces = document.getElementById("pieces");
  wrap.classList.toggle("board3", boardId === "3");

  const layout = BOARD_LAYOUTS[boardId];
  pieces.setAttribute("viewBox", `0 0 ${layout.viewBox.w} ${layout.viewBox.h}`);

  const boardJson = await fetchJson(`/assets/boards/board${boardId}.json`);
  if (boardId === "3") {
    const r = await fetch(`/assets/boards/${boardJson.blank_svg || "board3_blank.svg"}`);
    host.innerHTML = await r.text();
  } else if (boardJson.physical_image) {
    host.innerHTML = `<img src="/assets/boards/${boardJson.physical_image}" alt="Board ${boardId}"/>`;
  } else {
    host.innerHTML = `<div>Board ${boardId}</div>`;
  }
}

function movePiece(player, tileIndex, boardId) {
  const layout = BOARD_LAYOUTS[boardId];
  const coords = layout?.centers?.[tileIndex];
  if (!coords) return;
  const [cx, cy] = coords;
  const el = document.getElementById(`piece-${player}`);
  el.setAttribute("cx", cx);
  el.setAttribute("cy", cy);
  if (player === "robot") el.setAttribute("transform", "translate(-36 0)");
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
  document.getElementById("st-fsm").textContent = state.fsm;
  document.getElementById("st-turn").textContent = state.turn;
  document.getElementById("st-num").textContent = state.turn_number;
  document.getElementById("st-winner").textContent = state.winner || "—";
  // Single-die manual input stores as (value, 0); only render the "+ d2"
  // part when we actually rolled two dice (Board 2 doubles detection).
  const ld = state.last_dice;
  document.getElementById("st-dice").textContent = !ld
    ? "—"
    : ld[1] > 0
      ? `${ld[0]} + ${ld[1]} = ${state.last_dice_sum}`
      : String(ld[0]);

  for (const p of ["user", "robot"]) {
    const pos = state.positions[p];
    if (pos !== undefined) movePiece(p, pos, state.board_id);
  }
  const money = {};
  for (const [pid, ps] of Object.entries(state.players || {})) money[pid] = ps.balance;
  renderMoney(money);

  const winner = state.winner;
  document.getElementById("btn-apply-move").disabled = state.fsm !== "MOVING";
  document.getElementById("btn-submit-dice").disabled = state.fsm !== "TURN_START";
  document.getElementById("btn-end-turn").disabled =
    !["RESOLVE_TILE", "END_TURN"].includes(state.fsm) || winner;
}

async function refreshState() {
  currentState = await fetchJson("/api/game/state");
  renderState(currentState);
  if (currentState.board_id === "1" || currentState.board_id === "2") {
    try {
      const props = await fetchJson("/api/properties");
      renderPropertyLists(props);
    } catch (err) { /* properties empty before start */ }
  }
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

document.getElementById("btn-start").addEventListener("click", async () => {
  const board = document.getElementById("board-select").value;
  await loadBoardVisual(board);
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
document.getElementById("btn-skip").addEventListener("click", () => submitDecision("skip"));
document.getElementById("btn-buy").addEventListener("click", () => submitDecision("buy"));
document.getElementById("btn-buy-build").addEventListener("click", () => submitDecision("build", 1));

// ---- boot -----------------------------------------------------------------

(async () => {
  await refreshBadges();
  setInterval(refreshBadges, 5000);
  await loadBoardVisual("3");
  await refreshState();
  openStream();
})();
