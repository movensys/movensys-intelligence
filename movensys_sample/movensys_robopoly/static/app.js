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

// Ownership circles overlay: for each owned property, draw 1/2/3 colored
// circles next to that tile — 1=land, 2=house, 3=hotel. Red=user, green=robot.
function renderOwnership(state) {
  const svg = document.getElementById("pieces");
  if (!svg) return;
  const layout = BOARD_LAYOUTS[state?.board_id];
  let g = document.getElementById("ownership-overlay");
  if (g) g.replaceChildren();
  if (!layout) return;
  if (!g) {
    g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("id", "ownership-overlay");
    svg.insertBefore(g, svg.firstChild);  // behind pieces
  }
  const props = state?.properties || {};
  for (const p of Object.values(props)) {
    if (!p.owner) continue;
    const tile = layout.centers?.[p.tile_index];
    if (!tile) continue;
    const cx = (tile.user[0] + tile.robot[0]) / 2;
    const cy = (tile.user[1] + tile.robot[1]) / 2 + 22;  // just below the pieces
    const tier = p.has_hotel ? 3 : (p.houses > 0 ? 2 : 1);
    const fill = p.owner === "user" ? "var(--user)" : "var(--robot)";
    const r = 21, gap = 12;
    const totalW = tier * 2 * r + (tier - 1) * gap;
    const startX = cx - totalW / 2 + r;
    for (let i = 0; i < tier; i++) {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", String(startX + i * (2 * r + gap)));
      c.setAttribute("cy", String(cy));
      c.setAttribute("r", String(r));
      c.setAttribute("fill", fill);
      c.setAttribute("stroke", "#000");
      c.setAttribute("stroke-width", "4.5");
      g.appendChild(c);
    }
  }
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
function renderMoney(liquidSnap, assetsSnap) {
  for (const p of ["user", "robot"]) {
    const el = document.getElementById(`money-${p}-value`);
    const prev = lastBalance[p];
    const curr = liquidSnap[p] ?? 0;
    el.textContent = `$${curr}`;
    if (prev !== null && curr !== prev) {
      el.classList.remove("flash-up", "flash-down");
      void el.offsetWidth; // reflow so animation replays
      el.classList.add(curr > prev ? "flash-up" : "flash-down");
      setTimeout(() => el.classList.remove("flash-up", "flash-down"), 600);
    }
    lastBalance[p] = curr;

    const aEl = document.getElementById(`money-${p}-assets`);
    if (aEl) aEl.textContent = `$${assetsSnap?.[p] ?? 0}`;
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
  const currentTier = decision.current_tier ?? 0;
  const maxTier = decision.max_tier ?? (card.kind === "property" ? 3 : 1);
  const tierLabel = ["unowned", "land", "house", "hotel"];
  const host = document.getElementById("decision-card");
  const subtitle = currentTier > 0
    ? `You already own this — current tier: ${tierLabel[currentTier]}`
    : "Unowned — pick a tier to buy directly";
  host.innerHTML = `
    <div class="card-preview">
      <div class="kind">${card.kind}</div>
      <div class="name">${card.name}</div>
      <div class="price">${subtitle}</div>
    </div>
  `;
  const title = currentTier > 0
    ? `Upgrade ${card.name}`
    : `Land on ${card.name}`;
  document.getElementById("decision-title").textContent = title;

  const btnBuy   = document.getElementById("btn-buy");        // → land  (tier 1)
  const btnHouse = document.getElementById("btn-buy-build");  // → house (tier 2)
  const btnHotel = document.getElementById("btn-buy-hotel");  // → hotel (tier 3)

  // Show only the upgrade paths that actually advance the tier.
  btnBuy.style.display   = currentTier < 1 ? "inline-block" : "none";
  btnHouse.style.display = (currentTier < 2 && maxTier >= 2) ? "inline-block" : "none";
  btnHotel.style.display = (currentTier < 3 && maxTier >= 3) ? "inline-block" : "none";

  // Re-label with the actual delta cost from where the player is now.
  btnBuy.textContent   = "Buy land ($100)";
  btnHouse.textContent = `Buy + house ($${(2 - currentTier) * 100})`;
  btnHotel.textContent = `Buy + hotel ($${(3 - currentTier) * 100})`;

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
  // Spec §3.4: end-turn is automatic. After the buy/skip/build choice
  // the FSM is back at RESOLVE_TILE, so end_turn is safe to call.
  try {
    await postJson("/api/game/end_turn");
  } catch (err) {
    console.warn("post-decide end_turn:", err);
  } finally {
    turnInFlight = false;
  }
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
    case "property_built": {
      const label = payload.tier_label || (payload.tier === 3 ? "hotel" : "house");
      announce(`Built ${label} on ${propertyName(payload.property_id)}`, "build");
      break;
    }
    case "tier_sold": {
      const labels = ["unowned", "land", "house", "hotel"];
      const what = labels[payload.from_tier] || "tier";
      announce(`Sold ${what} on ${propertyName(payload.property_id)} (+$${payload.refund})`, "money");
      break;
    }
    case "tile_rent_paid":
      announce(`Rent paid${payload.amount ? ` ($${payload.amount})` : ""}`, "money");
      break;
    case "tile_tax_paid":
      announce(`Tax paid${payload.amount ? ` ($${payload.amount})` : ""}`, "money");
      break;
    case "chance_drawn": {
      const dir = payload.direction;
      const amt = payload.amount;
      if (dir === "collect") announce(`Chance: collect $${amt}`, "money");
      else if (dir === "pay") announce(`Chance: pay $${Math.abs(amt)}`, "money");
      break;
    }
    case "jail_escaped":
      announce(`${payload.player} rolled 6 and escaped jail!`, "turn");
      break;
    case "jail_skipped":
      announce(`${payload.player} is in jail (${payload.turns_left} turn(s) left)`, "money");
      break;
    case "jail_released":
      announce(`${payload.player} served their time and is free`, "turn");
      break;
    case "game_won":
      if (payload.draw) {
        const t = payload.totals || {};
        announce(`🤝 Draw — both players at $${t.user ?? "?"}`, "win");
      } else {
        const reason = payload.reason === "lap_cap" ? " (5 laps)" : "";
        announce(`🏆 ${payload.winner} wins the game!${reason}`, "win");
      }
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
// Spec §3: one button drives the whole turn. This flag gates Roll-dice
// while the roll → move → resolve → end-turn chain is in flight (including
// while the Buy modal is open waiting for a choice).
let turnInFlight = false;

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
  renderOwnership(state);
  const money = {};
  const assets = { user: 0, robot: 0 };
  for (const [pid, ps] of Object.entries(state.players || {})) money[pid] = ps.balance;
  for (const p of Object.values(state.properties || {})) {
    if (!p.owner) continue;
    const tier = p.has_hotel ? 3 : (p.houses > 0 ? 2 : 1);
    assets[p.owner] = (assets[p.owner] ?? 0) + tier * 100;
  }
  renderMoney(money, assets);

  const winner = state.winner;
  // Spec §3: Roll dice is the only turn button; it chains move + end-turn
  // automatically. Disabled while a turn is in flight or a buy modal is open.
  document.getElementById("btn-roll-dice").disabled =
    state.fsm !== "TURN_START" || winner || turnInFlight;

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
  if (typeof maybeAutoTriggerRobotTurn === "function") maybeAutoTriggerRobotTurn();
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
      if (typeof maybeAutoTriggerRobotTurn === "function") maybeAutoTriggerRobotTurn();
      return;
    }
    if (env.type === "tile_property_arrival_buyable" && env.payload.needs_decision) {
      showDecision({
        property_id: env.payload.property_id,
        card: env.payload.card,
        current_tier: env.payload.current_tier ?? 0,
        max_tier: env.payload.max_tier,
      });
    }
    announceFromEvent(env);
    await refreshState();
  };
  ws.onclose = () => setTimeout(openStream, 1500);
  ws.onerror = () => ws.close();
}

// ---- manual controls ------------------------------------------------------

// Spec §3: Roll dice chains roll → physical move → tile resolution → end turn.
// The only pause for human input is the Buy modal (§4.1.1 / §4.1.2); rent,
// tax, chance, and auto-liquidation all resolve server-side.
document.getElementById("btn-roll-dice").addEventListener("click", async () => {
  if (turnInFlight) return;
  const btn = document.getElementById("btn-roll-dice");
  const prevText = btn.textContent;
  turnInFlight = true;
  btn.disabled = true;
  btn.textContent = "Rolling…";

  try {
    // 1. Roll the dice (physical arm).
    const rollRes = await postJson("/api/dice/roll_robot", { is_YOLO: isYOLO });
    if (rollRes && typeof rollRes.dice_number === "number") {
      renderDiceFace(rollRes.dice_number);
    }

    // 1b. Jail-skip path: rules.submit_dice transitions straight to END_TURN
    //     when the jailed player rolls a non-6 with turns_left > 0.
    if (rollRes && rollRes.fsm === "END_TURN") {
      await postJson("/api/game/end_turn");
      return;
    }
    if (!rollRes || rollRes.fsm !== "MOVING") {
      console.warn("roll_robot: unexpected fsm", rollRes && rollRes.fsm);
      return;
    }

    // 2. Apply move (physical arm). Compute destination from the current
    //    player's tile + dice sum, modulo the board size.
    const player = currentState && currentState.turn;
    if (!player || !currentState) {
      console.warn("apply_robot: missing currentState");
      return;
    }
    const from = currentState.positions[player];
    const size = BOARD_LAYOUTS[currentState.board_id]
      ? Object.keys(BOARD_LAYOUTS[currentState.board_id].centers).length
      : 40;
    const to = (from + rollRes.sum) % size;
    btn.textContent = "Moving…";
    const moveRes = await postJson("/api/move/apply_robot", {
      player, from_tile: from, to_tile: to, is_YOLO: isYOLO,
    });

    // 3. If the tile arrival needs a human decision (Buy modal), stop here.
    //    The WS event already popped the modal; submitDecision will call
    //    end_turn after the user picks an option.
    if (moveRes && moveRes.fsm === "AWAIT_DECISION") {
      return;
    }

    // 4. Auto end-turn — rent / tax / chance / bankruptcy already resolved
    //    inside apply_move on the server side.
    await postJson("/api/game/end_turn");
  } catch (err) {
    console.warn("roll-dice chain:", err);
  } finally {
    btn.textContent = prevText;
    // Re-enable when the chain stops here (errors, jail-skip, or end_turn).
    // If we're still mid-modal (AWAIT_DECISION), keep the flag set —
    // submitDecision will clear it after the post-modal end_turn lands.
    if (!currentState || currentState.fsm !== "AWAIT_DECISION") {
      turnInFlight = false;
    }
  }
});
document.getElementById("btn-reset").addEventListener("click", async () => {
  turnInFlight = false;
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
document.getElementById("btn-buy-hotel").addEventListener("click", () => submitDecision("build_hotel"));

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
    // Spec doc/vlm_as_player.md §4.2: when the user types during their
    // TURN_START, the textbox is the user-turn trigger — route the message
    // through the VLM-player action loop instead of the free-form Q&A path.
    if (currentState && currentState.turn === "user"
        && currentState.fsm === "TURN_START" && !currentState.winner) {
      const msg = (prompt.value || "").trim() || "I rolled the dice.";
      inFlight = true;
      askBtn.disabled = true;
      askBtn.textContent = "Playing…";
      respEl.className = "vlm-response";
      respEl.textContent = "Acting on your turn…";
      try {
        await vlmPlayerAct(msg);
        respEl.textContent = "(turn dispatched)";
        const ts = new Date().toLocaleTimeString();
        metaEl.textContent = ts;
      } catch (err) {
        respEl.className = "vlm-response error";
        respEl.textContent = String(err);
      } finally {
        inFlight = false;
        askBtn.disabled = false;
        askBtn.textContent = "Ask";
      }
      return;
    }
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

// ==== VLM as robot player (doc/vlm_as_player.md) ===========================
// Single agent loop: the orchestrator's VLM plays the "robot" side. On the
// user's turn the user types in the Ask VLM textbox to nudge the same agent;
// on the robot's turn the agent fires automatically. The VLM never touches
// the arm directly — it emits a JSON action and the frontend dispatches it
// through the existing /api endpoints (so all rules / pick-and-place logic
// stay server-side).

const VLM_PLAYER_SYSTEM_PROMPT = `You are a game-playing AGENT for robopoly, a 2-player Monopoly-style game.
You are an action-emitter for an automated game loop.

Each prompt may include a top-down image of the physical board AND a JSON
state snapshot. The JSON state is the source of truth for your decision —
the image is additional grounding only. Do NOT describe the image. Do NOT
explain what you see. Do NOT refuse with "I cannot roll dice" — you ARE
rolling the dice by emitting the JSON action below; the code reads it and
tells the arm to act.

Players: "user" (red cube), "robot" (you, green cube). Turns alternate.

OUTPUT FORMAT — strict:
  Your entire reply MUST be a single JSON object. No prose. No greetings.
  No apologies. No markdown. No code fences. No explanation of capabilities.
  If you reply with anything other than one JSON object, the turn FAILS.

ACTIONS — exactly two are valid:

1. {"action": "roll_and_move", "player": "user"}
   {"action": "roll_and_move", "player": "robot"}
     Use when fsm == "TURN_START". "player" MUST equal state.turn.

2. {"action": "decide", "choice": "skip"}
   {"action": "decide", "choice": "buy"}
   {"action": "decide", "choice": "build"}
   {"action": "decide", "choice": "build_hotel"}
     Use when state.decision_pending is present (fsm == "AWAIT_DECISION").
       buy         → buy land for $100
       build       → upgrade to house tier (delta = (2 - current_tier) * 100)
       build_hotel → upgrade to hotel tier (delta = (3 - current_tier) * 100)
       skip        → pass

EXAMPLES (these are the entire reply — nothing else):
  {"action": "roll_and_move", "player": "robot"}
  {"action": "decide", "choice": "buy"}

DO NOT reply with text like "I cannot roll dice" — you ARE rolling the dice
by emitting the JSON. The code reads your JSON and tells the arm to act.

RULES (for choosing actions):
- Seed money $1000; GO bonus $100 (passing or landing).
- Tiers: land $100, house $200, hotel $300. Rent: $100 / $200 / $300 by tier.
- Tax tile $100. Chance: ±$200 coin flip.
- Auto-liquidation: hotels → houses → land if you can't pay.
- 5 laps wins on cap; bankruptcy ends the game immediately.

BUY HEURISTICS (apply unless state says otherwise):
- liquid >= $300 → buy
- liquid >= $400 and already owned at tier 1 → build (house)
- liquid >= $500 and already owned at tier 2 → build_hotel
- purchase would drop liquid below $200 → skip

Reply with ONLY the JSON action. Nothing else.`;

let vlmPlayerInFlight = false;
let vlmPlayerLastTurnKey = null;

// Top-down board camera. The orchestrator grabs the latest /image_top/rgb
// frame and sends it alongside the prompt — this gives the VLM visual
// grounding instead of relying on the state JSON alone. If the camera is
// not publishing, the orchestrator silently degrades to text-only.
const VLM_PLAYER_CAMERA = "top";

async function vlmInferRaw(prompt) {
  const r = await fetch(`${VLM_BASE}/api/vlm/infer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ camera: VLM_PLAYER_CAMERA, prompt, client: "robopoly" }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${r.status}`);
  }
  const body = await r.json();
  return body.response || "";
}

function parseVlmAction(text) {
  if (!text) return null;
  // Strip any ```json … ``` fences the model may emit despite the system prompt.
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = (fenced ? fenced[1] : text).trim();
  // Take the first balanced { … } block.
  const m = candidate.match(/\{[\s\S]*\}/);
  if (!m) return null;
  try { return JSON.parse(m[0]); } catch { return null; }
}

function buildVlmStateSummary(state) {
  const summary = {
    turn: state.turn,
    fsm: state.fsm,
    turn_number: state.turn_number,
    positions: { ...(state.positions || {}) },
    balances: {},
    lap_count: { ...(state.lap_count || {}) },
    properties_owned: { user: [], robot: [] },
    last_dice: state.last_dice,
    last_dice_sum: state.last_dice_sum,
  };
  for (const [pid, ps] of Object.entries(state.players || {})) {
    summary.balances[pid] = ps.balance;
  }
  for (const p of Object.values(state.properties || {})) {
    if (!p.owner) continue;
    const tier = p.has_hotel ? 3 : (p.houses > 0 ? 2 : 1);
    summary.properties_owned[p.owner].push({ id: p.id, tile_index: p.tile_index, tier });
  }
  if (pendingDecision) {
    summary.decision_pending = {
      property_id: pendingDecision.property_id,
      current_tier: pendingDecision.current_tier ?? 0,
      max_tier: pendingDecision.max_tier ?? 3,
    };
  }
  return summary;
}

async function executeVlmAction(action) {
  if (!action || typeof action !== "object") return false;
  if (action.action === "roll_and_move") {
    // Reuse the existing Roll-dice chain — it handles roll, physical move,
    // tile resolution, auto-rent, auto-jail PnP, and auto end-turn.
    const btn = document.getElementById("btn-roll-dice");
    if (btn && !btn.disabled) { btn.click(); return true; }
    return false;
  }
  if (action.action === "decide") {
    const c = action.choice;
    if (c === "build") { await submitDecision("build", 1); return true; }
    if (["skip", "buy", "build_hotel"].includes(c)) {
      await submitDecision(c);
      return true;
    }
    return false;
  }
  return false;
}

// Always inline the action grammar in the user message too, so the model
// can't drift into a "vision assistant, I cannot roll dice" refusal even if
// the per-client system prompt got overridden somewhere upstream.
const VLM_PLAYER_INLINE_RULES = `You are the game agent. Reply with EXACTLY ONE JSON object — no prose, no fences, no apology.
Valid replies are ONLY:
  {"action": "roll_and_move", "player": "user"}
  {"action": "roll_and_move", "player": "robot"}
  {"action": "decide", "choice": "buy"}
  {"action": "decide", "choice": "build"}
  {"action": "decide", "choice": "build_hotel"}
  {"action": "decide", "choice": "skip"}
You are NOT a vision assistant. You are NOT asked to read images or physically roll dice.
The arm executes whatever JSON you emit. If fsm == "TURN_START" pick roll_and_move with player = state.turn.
If state.decision_pending is set, pick a decide action. Reply with ONLY the JSON, nothing else.`;

async function vlmPlayerAct(userMessage) {
  if (vlmPlayerInFlight) return;
  if (!currentState) return;
  vlmPlayerInFlight = true;
  try {
    const summary = buildVlmStateSummary(currentState);
    const prompt =
      `${VLM_PLAYER_INLINE_RULES}\n\n` +
      `Context: ${userMessage}\n\n` +
      `State:\n${JSON.stringify(summary, null, 2)}\n\n` +
      `Your reply (ONE JSON object, nothing else):`;
    const resp = await vlmInferRaw(prompt);
    const action = parseVlmAction(resp);
    if (!action) {
      console.warn("[vlm-player] no parseable action in:", resp);
      return;
    }
    await executeVlmAction(action);
  } catch (err) {
    console.warn("[vlm-player]:", err);
  } finally {
    vlmPlayerInFlight = false;
  }
}

// Auto-trigger on robot's TURN_START or AWAIT_DECISION. Idempotent per
// (turn, fsm, turn_number, pending_property) so we don't spam the VLM on
// every WS event during the same logical step.
function maybeAutoTriggerRobotTurn() {
  if (!currentState || currentState.winner) return;
  if (currentState.turn !== "robot") return;
  const pendingPid = pendingDecision ? pendingDecision.property_id : "";
  const key = `${currentState.turn}|${currentState.fsm}|${currentState.turn_number}|${pendingPid}`;
  if (vlmPlayerLastTurnKey === key) return;
  if (currentState.fsm === "TURN_START") {
    vlmPlayerLastTurnKey = key;
    vlmPlayerAct("It's your turn (robot). Roll the dice and move your cube.");
  } else if (currentState.fsm === "AWAIT_DECISION" && pendingDecision) {
    vlmPlayerLastTurnKey = key;
    vlmPlayerAct("You landed on a buyable property. Decide buy / build / build_hotel / skip.");
  }
}

async function ensureVlmPlayerSystemPrompt() {
  // Always install the agent prompt on boot — otherwise a leftover
  // vision-assistant prompt can cause the VLM to refuse with
  // "I cannot physically roll dice for you" instead of emitting the
  // JSON action. The user can still edit the prompt afterwards via
  // the Ask VLM sidebar's system-prompt editor.
  try {
    await fetch(`${VLM_BASE}/api/vlm/system_prompt?client=robopoly`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: VLM_PLAYER_SYSTEM_PROMPT }),
    });
  } catch (err) {
    console.warn("[vlm-player] system prompt setup:", err);
  }
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
  await ensureVlmPlayerSystemPrompt();
  // First call after we have a snapshot — kicks the robot if the saved
  // state already has turn=robot on load.
  maybeAutoTriggerRobotTurn();
})();
