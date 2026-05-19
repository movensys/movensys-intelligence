/**
 * movensys-monopoly UI.
 *
 * 14-tile JSON model rendered on a 14-cell rectangular perimeter (5 wide × 4
 * tall grid). Indexing is counter-clockwise from GO at the bottom-left
 * corner. viewBox matches board.png (PDF page 1559 × 794 → ≈ 1.96:1).
 */

// Cell geometry, corners 1.5× side cells:
//   width  units: 1.5 + 1 + 1 + 1 + 1.5 = 6 → unit ≈ 259.83
//   height units: 1.5 + 1 + 1 + 1.5     = 5 → unit ≈ 158.80
//   corner ≈ 390×238, top/bot side ≈ 260×238, left/right side ≈ 390×159
//
// Piece centers below sit at the geometric centre of each cell. The pieces
// in #pieces are pointer-draggable (see setupPieceDragging) so the
// operator can fine-tune on the printed board and read the new coords off
// the board-coords readout.
const BOARD_FINAL_LAYOUT = {
  viewBox: { w: 1559, h: 794 },
  centers: {
    0:  { user: [81.06,   710.60], robot: [165.93, 710.60] },  // GO (BL)
    1:  { user: [63.20,   545.48], robot: [148.08, 545.48] },  // BOSTON (left, lower mid)
    2:  { user: [63.20,   344.65], robot: [146.59, 344.65] },  // SEOUL (left, upper mid)
    3:  { user: [63.20,   146.79], robot: [148.08, 146.79] },  // IN THE DESERT ISLAND (TL)
    4:  { user: [372.63,  143.82], robot: [453.04, 143.82] },  // ELECTRIC COMPANY (top)
    5:  { user: [689.50,  143.82], robot: [774.37, 143.82] },  // TAIPEI (top)
    6:  { user: [998.92,  146.79], robot: [1086.88, 146.90] }, // SHANGHAI (top)
    7:  { user: [1311.69, 146.79], robot: [1391.94, 146.90] }, // NON-FREE PARKING (TR)
    8:  { user: [1299.36, 342.46], robot: [1379.62, 341.03] }, // TOKYO (right, upper mid)
    9:  { user: [1297.82, 542.76], robot: [1385.78, 542.86] }, // BUSAN (right, lower mid)
    10: { user: [1300.91, 739.97], robot: [1385.78, 738.53] }, // GO TO DESERT ISLAND (BR)
    11: { user: [992.76,  739.97], robot: [1076.10, 740.07] }, // NEW YORK (bottom)
    12: { user: [678.45,  741.51], robot: [757.17, 740.07] },  // CHANCE (bottom)
    13: { user: [368.77,  739.97], robot: [447.48, 740.07] },  // LONDON (bottom)
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

// Cell horizontal extent per tile, used to size the ownership rectangle
// (~65% of the cell width). Corners and left/right edges are narrower; the
// inner top/bottom edges are wider.
const TILE_CELL_WIDTH = {
  0: 240, 1: 240, 2: 240, 3: 240,
  4: 320, 5: 320, 6: 320,
  7: 240, 8: 240, 9: 240, 10: 240,
  11: 320, 12: 320, 13: 320,
};
const PIECE_HEIGHT = 60;
const OWNERSHIP_LABELS = [
  "GO", "BOSTON", "SEOUL", "DESERT",
  "ELECTRIC", "TAIPEI", "SHANGHAI",
  "PARKING", "TOKYO", "BUSAN",
  "GO_DESERT", "NEWYORK", "CHANCE", "LONDON",
];
// Tiles that do not display an ownership rectangle.
const OWNERSHIP_HIDDEN = new Set([0, 3, 7, 10, 12]);
// Per-tile rectangle size override [width, height]. Tiles without an entry
// use the default size (cell_width * 0.65 wide × piece_height/2 tall).
// ELECTRIC uses a smaller utility-style box: width 110% of the piece width,
// height 65% of the piece height.
const OWNERSHIP_RECT_SIZE = {
  4: [PIECE_HEIGHT * 1.1, PIECE_HEIGHT * 0.65],
};
// Calibrated rectangle centers per tile (in viewBox coords). Tiles without
// an entry default to a position just below the pieces and rely on the
// operator dragging to calibrate.
const OWNERSHIP_CENTERS = {
  1:  [99.48,   478.39],
  2:  [98.73,   274.47],
  4:  [553.04,  48.87],
  5:  [744.26,  82.89],
  6:  [1055.23, 82.83],
  8:  [1342.57, 276.19],
  9:  [1340.26, 477.26],
  11: [1056.00, 671.38],
  13: [431.24,  674.47],
};

// Pre-create one <g id="ownership-{idx}"> per tile, each containing a rect
// + text label. The group is positioned by a transform="translate(dx,dy)"
// that the operator can drag-tune; the rect/text keep stable base coords
// so renderOwnership only needs to update fill+label, leaving any dragged
// translate intact.
function setupOwnershipRects() {
  const svg = document.getElementById("pieces");
  if (!svg) return;
  let overlay = document.getElementById("ownership-overlay");
  if (overlay) overlay.remove();
  overlay = document.createElementNS("http://www.w3.org/2000/svg", "g");
  overlay.setAttribute("id", "ownership-overlay");
  svg.insertBefore(overlay, svg.firstChild);

  const layout = BOARD_LAYOUTS["final"];
  if (!layout) return;
  for (let idx = 0; idx < 14; idx++) {
    if (OWNERSHIP_HIDDEN.has(idx)) continue;
    const tile = layout.centers[idx];
    if (!tile) continue;
    const sizeOverride = OWNERSHIP_RECT_SIZE[idx];
    const rectW = sizeOverride ? sizeOverride[0] : (TILE_CELL_WIDTH[idx] ?? 240) * 0.65;
    const rectH = sizeOverride ? sizeOverride[1] : PIECE_HEIGHT / 2;
    const center = OWNERSHIP_CENTERS[idx];
    const rectCx = center ? center[0] : (tile.user[0] + tile.robot[0]) / 2;
    const rectCy = center
      ? center[1]
      : (tile.user[1] + tile.robot[1]) / 2 + PIECE_HEIGHT / 2 + 5 + rectH / 2;
    const rectX = rectCx - rectW / 2;
    const rectY = rectCy - rectH / 2;

    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("id", `ownership-${idx}`);
    g.setAttribute("class", "ownership-group unowned");
    g.setAttribute("transform", "translate(0,0)");
    g.dataset.tileIndex = String(idx);

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", String(rectX));
    rect.setAttribute("y", String(rectY));
    rect.setAttribute("width", String(rectW));
    rect.setAttribute("height", String(rectH));
    rect.setAttribute("fill", "rgba(180,180,180,0.30)");
    rect.setAttribute("stroke", "#555");
    rect.setAttribute("stroke-width", "2");
    rect.setAttribute("stroke-dasharray", "5 3");
    g.appendChild(rect);

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", String(rectCx));
    text.setAttribute("y", String(rectCy));
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("dominant-baseline", "central");
    text.setAttribute("fill", "#fff");
    text.setAttribute("font-family", "JetBrains Mono, ui-monospace, monospace");
    text.setAttribute("font-size", "20");
    text.setAttribute("font-weight", "700");
    text.setAttribute("paint-order", "stroke");
    text.setAttribute("stroke", "#000");
    text.setAttribute("stroke-width", "3");
    text.setAttribute("stroke-linejoin", "round");
    text.setAttribute("pointer-events", "none");
    text.textContent = "";
    g.appendChild(text);

    overlay.appendChild(g);
  }
}

// Ownership overlay refresh: just toggle fill/stroke/label per tile based
// on the current state. The 14 groups are created once by
// setupOwnershipRects() and stay drag-tunable across state updates.
function renderOwnership(state) {
  const props = state?.properties || {};
  const byTile = {};
  for (const p of Object.values(props)) {
    if (p && p.tile_index !== undefined) byTile[p.tile_index] = p;
  }
  for (let idx = 0; idx < 14; idx++) {
    const g = document.getElementById(`ownership-${idx}`);
    if (!g) continue;
    const rect = g.querySelector("rect");
    const text = g.querySelector("text");
    if (!rect || !text) continue;
    const p = byTile[idx];
    if (p && p.owner) {
      const fill = p.owner === "user" ? "var(--user)" : "var(--robot)";
      const label = p.has_hotel ? "HOTEL" : (p.houses > 0 ? "HOUSE" : "LAND");
      rect.setAttribute("fill", fill);
      rect.setAttribute("stroke", "#000");
      rect.setAttribute("stroke-width", "2.5");
      rect.removeAttribute("stroke-dasharray");
      text.textContent = label;
      g.classList.remove("unowned");
    } else {
      rect.setAttribute("fill", "rgba(180,180,180,0.30)");
      rect.setAttribute("stroke", "#555");
      rect.setAttribute("stroke-width", "2");
      rect.setAttribute("stroke-dasharray", "5 3");
      text.textContent = "";
      g.classList.add("unowned");
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

  const parseTranslate = (el) => {
    const tr = el.getAttribute("transform") || "";
    const m = tr.match(/translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)/);
    return m ? [parseFloat(m[1]), parseFloat(m[2])] : [0, 0];
  };

  const rectBaseCenter = (rect) => {
    const x = parseFloat(rect.getAttribute("x"));
    const y = parseFloat(rect.getAttribute("y"));
    const w = parseFloat(rect.getAttribute("width"));
    const h = parseFloat(rect.getAttribute("height"));
    return [x + w / 2, y + h / 2];
  };

  const pieceCenter = (rect) => {
    const [bcx, bcy] = rectBaseCenter(rect);
    const [tx, ty] = parseTranslate(rect);
    return [bcx + tx, bcy + ty];
  };

  const ownershipCenter = (g) => {
    const rect = g.querySelector("rect");
    if (!rect) return [0, 0];
    const [bcx, bcy] = rectBaseCenter(rect);
    const [tx, ty] = parseTranslate(g);
    return [bcx + tx, bcy + ty];
  };

  const fmt = (n) => n.toFixed(2);

  updatePieceReadout = () => {
    const [ux, uy] = pieceCenter(userRect);
    const [rx, ry] = pieceCenter(robotRect);
    const lines = [
      `user: (${fmt(ux)}, ${fmt(uy)})  |  robot: (${fmt(rx)}, ${fmt(ry)})`,
    ];
    const parts = [];
    for (let idx = 0; idx < 14; idx++) {
      const g = document.getElementById(`ownership-${idx}`);
      if (!g) continue;
      const [cx, cy] = ownershipCenter(g);
      parts.push(`${OWNERSHIP_LABELS[idx]}: (${fmt(cx)}, ${fmt(cy)})`);
    }
    for (let i = 0; i < parts.length; i += 4) {
      lines.push(parts.slice(i, i + 4).join("  |  "));
    }
    readout.textContent = lines.join("\n");
  };

  const svgPoint = (evt) => {
    const pt = pieces.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    return pt.matrixTransform(pieces.getScreenCTM().inverse());
  };

  let dragging = null;
  let dragOffset = { x: 0, y: 0 };

  const wirePiece = (rect) => {
    rect.addEventListener("pointerdown", (evt) => {
      dragging = { kind: "piece", handle: rect };
      rect.classList.add("dragging");
      const pt = svgPoint(evt);
      const [cx, cy] = pieceCenter(rect);
      dragOffset.x = pt.x - cx;
      dragOffset.y = pt.y - cy;
      rect.setPointerCapture(evt.pointerId);
      evt.preventDefault();
    });
    rect.addEventListener("pointermove", (evt) => {
      if (!dragging || dragging.handle !== rect) return;
      const pt = svgPoint(evt);
      const newCx = pt.x - dragOffset.x;
      const newCy = pt.y - dragOffset.y;
      const w = parseFloat(rect.getAttribute("width"));
      const h = parseFloat(rect.getAttribute("height"));
      const [tx, ty] = parseTranslate(rect);
      rect.setAttribute("x", newCx - w / 2 - tx);
      rect.setAttribute("y", newCy - h / 2 - ty);
      updatePieceReadout();
    });
    const stop = (evt) => {
      if (!dragging || dragging.handle !== rect) return;
      dragging = null;
      rect.classList.remove("dragging");
      try { rect.releasePointerCapture(evt.pointerId); } catch (_) {}
    };
    rect.addEventListener("pointerup", stop);
    rect.addEventListener("pointercancel", stop);
  };

  const wireOwnership = (g) => {
    const rect = g.querySelector("rect");
    if (!rect) return;
    rect.addEventListener("pointerdown", (evt) => {
      dragging = { kind: "ownership", handle: rect, group: g };
      g.classList.add("dragging");
      rect.classList.add("dragging");
      const pt = svgPoint(evt);
      const [cx, cy] = ownershipCenter(g);
      dragOffset.x = pt.x - cx;
      dragOffset.y = pt.y - cy;
      rect.setPointerCapture(evt.pointerId);
      evt.preventDefault();
    });
    rect.addEventListener("pointermove", (evt) => {
      if (!dragging || dragging.handle !== rect) return;
      const pt = svgPoint(evt);
      const newCx = pt.x - dragOffset.x;
      const newCy = pt.y - dragOffset.y;
      const [bcx, bcy] = rectBaseCenter(rect);
      g.setAttribute("transform", `translate(${newCx - bcx},${newCy - bcy})`);
      updatePieceReadout();
    });
    const stop = (evt) => {
      if (!dragging || dragging.handle !== rect) return;
      dragging = null;
      g.classList.remove("dragging");
      rect.classList.remove("dragging");
      try { rect.releasePointerCapture(evt.pointerId); } catch (_) {}
    };
    rect.addEventListener("pointerup", stop);
    rect.addEventListener("pointercancel", stop);
  };

  wirePiece(userRect);
  wirePiece(robotRect);
  for (let idx = 0; idx < 14; idx++) {
    const g = document.getElementById(`ownership-${idx}`);
    if (g) wireOwnership(g);
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
  // Game mode: hold the result on screen before swapping turns —
  // STATUS_FLASH_MS for the buy/build flash to play out, then another 3s
  // of clean board view so the operator can take in the new building
  // before "It's robot's turn" overlays the screen.
  if (document.body.classList.contains("game-mode") && action !== "skip") {
    await new Promise((res) => setTimeout(res, STATUS_FLASH_MS + 3000));
  }
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

// Unified display duration for every status/state flash overlay.
const STATUS_FLASH_MS = 2000;
let gameOverlayTimer = null;
function flashGameOverlay(text, opts = {}) {
  const overlay = document.getElementById("game-overlay");
  const slot = document.getElementById("game-overlay-text");
  if (!overlay || !slot) return;
  // Status flash takes over the screen — close the chat overlay if open.
  document.body.classList.remove("chat-overlay-active");
  if (opts.html != null) slot.innerHTML = opts.html;
  else slot.textContent = text;
  overlay.classList.add("visible");
  if (gameOverlayTimer) clearTimeout(gameOverlayTimer);
  gameOverlayTimer = setTimeout(() => {
    overlay.classList.remove("visible");
    gameOverlayTimer = null;
  }, opts.durationMs ?? STATUS_FLASH_MS);
}

function isStatusOverlayActive() {
  const overlay = document.getElementById("game-overlay");
  return !!(overlay && overlay.classList.contains("visible"));
}

// Keywords that mark a transcribed Z-key utterance as a "show board state"
// request. We match a single character/word from this set so a question like
// "지금 몇 턴이지" or "show me the money" triggers the state flash.
const STATE_INQUIRY_RE = /(보드|상태|돈|머니|턴|board|state|status|money|turn|balance|cash)/i;
function isStateInquiry(text) {
  return !!text && STATE_INQUIRY_RE.test(text);
}
function flashCurrentStateOverlay() {
  if (!currentState) {
    flashGameOverlay("No game state yet");
    return;
  }
  const turn = currentState.turn_number ?? 0;
  const userBal = currentState.players?.user?.balance ?? 0;
  const robotBal = currentState.players?.robot?.balance ?? 0;
  const assets = { user: 0, robot: 0 };
  for (const p of Object.values(currentState.properties || {})) {
    if (!p.owner) continue;
    const tier = p.has_hotel ? 3 : (p.houses > 0 ? 2 : 1);
    assets[p.owner] = (assets[p.owner] ?? 0) + tier * 100;
  }
  const html =
    `Turn ${turn}\n` +
    `<span style="color: var(--user)">User</span>: $${userBal}  (assets $${assets.user})\n` +
    `<span style="color: var(--robot)">Robot</span>: $${robotBal}  (assets $${assets.robot})`;
  flashGameOverlay(null, { html, durationMs: 5000 });
}
function maybeOpenChatOverlay() {
  if (!document.body.classList.contains("game-mode")) return;
  if (isStatusOverlayActive()) return;
  document.body.classList.add("chat-overlay-active");
}
function closeChatOverlay() {
  document.body.classList.remove("chat-overlay-active");
}
function toggleChatOverlay() {
  if (document.body.classList.contains("chat-overlay-active")) closeChatOverlay();
  else maybeOpenChatOverlay();
}

function announce(text, kind = "info") {
  const el = document.getElementById("notification");
  if (el) {
    el.classList.remove("empty");
    el.className = `notification kind-${kind}`;
    el.textContent = text;
  }
  if (document.body.classList.contains("game-mode")) {
    flashGameOverlay(text);
  }
  // Mirror the same string into the chat transcript as a system bubble so
  // the operator sees turn changes / buys / etc. inline with the dialogue.
  // We only mirror the "high-signal" notifications that map to a single
  // chat-worthy event — the noisy ones (rent, tax, move spam) stay on the
  // banner only.
  const CHAT_KINDS = new Set(["turn", "win", "buy", "build"]);
  if (CHAT_KINDS.has(kind)) appendChat({ role: "sys", text });
}

// ---- chat transcript (Query & response panel) ----------------------------

const CHAT_BOTTOM_THRESHOLD = 40;
let chatStickToBottom = true;

function chatEl() { return document.getElementById("vlm-chat"); }

function appendChat({ role, text, meta = "", error = false, pending = false }) {
  const host = chatEl();
  if (!host) return null;
  // Lock scroll behaviour to whether the user is currently pinned to the
  // bottom — if they scrolled up to read history we don't drag them back.
  const distFromBottom = host.scrollHeight - host.scrollTop - host.clientHeight;
  const wasAtBottom = distFromBottom <= CHAT_BOTTOM_THRESHOLD;

  const msg = document.createElement("div");
  const classes = ["vlm-msg", role];
  if (error) classes.push("error");
  if (pending) classes.push("pending");
  msg.className = classes.join(" ");

  if (role !== "sys") {
    const role_el = document.createElement("div");
    role_el.className = "vlm-msg-role";
    role_el.textContent = role === "me" ? "you" : "vlm";
    msg.appendChild(role_el);
  }

  const body = document.createElement("div");
  body.textContent = text;
  msg.appendChild(body);

  if (meta) {
    const m = document.createElement("div");
    m.className = "vlm-msg-meta";
    m.textContent = meta;
    msg.appendChild(m);
  }
  host.appendChild(msg);
  if (wasAtBottom) host.scrollTop = host.scrollHeight;
  return msg;
}

function updateChatMsg(node, { text, meta, error = false, pending = false }) {
  if (!node) return;
  const bodyNode = node.querySelector("div:not(.vlm-msg-role):not(.vlm-msg-meta)");
  if (bodyNode && text !== undefined) bodyNode.textContent = text;
  const metaNode = node.querySelector(".vlm-msg-meta");
  if (meta !== undefined) {
    if (metaNode) metaNode.textContent = meta;
    else if (meta) {
      const m = document.createElement("div");
      m.className = "vlm-msg-meta";
      m.textContent = meta;
      node.appendChild(m);
    }
  }
  node.classList.toggle("error", !!error);
  node.classList.toggle("pending", !!pending);
  const host = chatEl();
  if (host) host.scrollTop = host.scrollHeight;
}

function setHotkeyState(text, isError = false) {
  const el = document.getElementById("vlm-hotkey-state");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("error", isError);
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
    case "tile_chance_drawn": {
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
      const decision = {
        property_id: env.payload.property_id,
        card: env.payload.card,
        current_tier: env.payload.current_tier ?? 0,
        max_tier: env.payload.max_tier,
      };
      // Robot decides via the VLM agent loop; keep the JS state but skip
      // the modal so the operator only ever sees buy choices for the user.
      if (currentState?.turn === "robot") pendingDecision = decision;
      else showDecision(decision);
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
    // 1. Get the dice value. Two paths depending on whose turn it is:
    //    - User turn  → /api/dice/read_robot. The human already threw the
    //      die by hand; the arm only moves to the scan pose so the camera
    //      has a clear view. No pickup, no drop.
    //    - Robot turn → /api/dice/roll_robot. The arm physically picks
    //      up, lifts, drops the die, then reads the rolled face.
    const diceEndpoint = (currentState && currentState.turn === "user")
      ? "/api/dice/read_robot"
      : "/api/dice/roll_robot";
    console.log("[roll-chain] dice step:",
      { endpoint: diceEndpoint, turn: currentState && currentState.turn });
    const rollRes = await postJson(diceEndpoint, { is_YOLO: isYOLO });
    console.log("[roll-chain] dice response:", rollRes);
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
      console.warn("[roll-chain] unexpected fsm:", rollRes && rollRes.fsm,
                   "— skipping apply_robot. Full response:", rollRes);
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
    console.log("[roll-chain] apply_robot:",
      { player, from_tile: from, to_tile: to, is_YOLO: isYOLO });
    const moveRes = await postJson("/api/move/apply_robot", {
      player, from_tile: from, to_tile: to, is_YOLO: isYOLO,
    });
    console.log("[roll-chain] apply_robot response:", moveRes);

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
    console.warn("[roll-chain] aborted with error:", err);
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
document.getElementById("btn-reset").addEventListener("click", () => {
  resetGame().catch((err) => console.warn("reset failed", err));
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
  const loopDot  = document.getElementById("vlm-loop-dot");
  const loopLbl  = document.getElementById("vlm-loop-status");

  let loopTimer = null;
  let inFlight  = false;

  async function askOnce() {
    if (inFlight) return;
    const userText = (prompt.value || "").trim();
    // Spec doc/vlm_as_player.md §4.2: when the user types during their
    // TURN_START, the textbox is the user-turn trigger — route the message
    // through the VLM-player action loop instead of the free-form Q&A path.
    const isUserTurnStart = currentState
      && currentState.turn === "user"
      && currentState.fsm === "TURN_START"
      && !currentState.winner;
    // Phrases that clearly mean "I'm trying to take my turn" — if the user
    // types one of these but the game isn't actually in user-TURN_START,
    // they're hitting the free-form Q&A path by accident and wondering
    // why nothing moves. Surface the real state instead of silently
    // forwarding the message to the VLM as a generic question.
    const looksLikeTurnIntent =
      /\b(roll|just rolled|i rolled|user roll|user just|my turn|moved?)\b/i.test(userText);
    if (!isUserTurnStart && looksLikeTurnIntent && currentState) {
      appendChat({ role: "me", text: userText });
      const reason = !currentState
        ? "no game state yet — start a new game"
        : currentState.winner
          ? `game is over (winner: ${currentState.winner}) — reset to play again`
          : currentState.turn !== "user"
            ? `it's ${currentState.turn}'s turn, not yours`
            : currentState.fsm !== "TURN_START"
              ? `fsm is "${currentState.fsm}", not "TURN_START" — a prior turn didn't finish. Try the Roll-dice button, Reset, or wait for the move to complete.`
              : "unknown gate failure";
      appendChat({
        role: "bot",
        text: `Can't dispatch your turn: ${reason}`,
        error: true,
        meta: new Date().toLocaleTimeString(),
      });
      prompt.value = "";
      return;
    }
    if (isUserTurnStart) {
      const msg = userText || "I rolled the dice.";
      inFlight = true;
      askBtn.disabled = true;
      askBtn.textContent = "Playing…";
      appendChat({ role: "me", text: msg });
      const pending = appendChat({ role: "bot", text: "Acting on your turn…", pending: true });
      try {
        await vlmPlayerAct(msg);
        updateChatMsg(pending, { text: "(turn dispatched)", meta: new Date().toLocaleTimeString() });
      } catch (err) {
        updateChatMsg(pending, { text: String(err), error: true });
      } finally {
        inFlight = false;
        askBtn.disabled = false;
        askBtn.textContent = "Ask";
        prompt.value = "";
      }
      return;
    }
    inFlight = true;
    askBtn.disabled = true;
    askBtn.textContent = "Thinking…";
    if (userText) appendChat({ role: "me", text: userText });
    const pending = appendChat({ role: "bot", text: "Waiting for VLM response…", pending: true });
    const started = performance.now();
    try {
      // Each Ask is a fresh standalone query: wipe the orchestrator's
      // vector-DB memory first so no prior turns leak into the LLM's
      // recall step. The chat UI still keeps the visible transcript.
      try {
        await fetch(`${VLM_BASE}/api/vlm/memory`, { method: "DELETE" });
      } catch (_) { /* memory clear is best-effort */ }
      const r = await fetch(`${VLM_BASE}/api/vlm/infer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera: "none", prompt: userText || null, client: "robopoly" }),
      });
      const body = await r.json();
      const elapsedMs = Math.round(performance.now() - started);
      if (!r.ok) {
        updateChatMsg(pending, {
          text: body.detail || `HTTP ${r.status}`,
          meta: `${elapsedMs} ms`,
          error: true,
        });
        return;
      }
      const ts = new Date().toLocaleTimeString();
      updateChatMsg(pending, {
        text: body.response || "(empty response)",
        meta: `${elapsedMs} ms · ${ts}`,
      });
    } catch (err) {
      updateChatMsg(pending, { text: String(err), error: true });
    } finally {
      inFlight = false;
      askBtn.disabled = false;
      askBtn.textContent = "Ask";
      prompt.value = "";
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
    form.append("language", "en");

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
      const rawText = (body.text || "").trim();
      const text = isWhisperHallucination(rawText) ? "" : rawText;
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

ACTION NAMES vs. BUTTON LABELS — the backend names do NOT match the
modal button labels; map carefully:
  backend "skip"         ↔ modal "Skip"
  backend "buy"          ↔ modal "Buy land"     (tier 1, total $100)
  backend "build"        ↔ modal "Buy + house"  (tier 2, total $200 from unowned)
  backend "build_hotel"  ↔ modal "Buy + hotel"  (tier 3, total $300 from unowned)
All three "buy*" options actually buy the land first if it's unowned.
The total cost is $100 × target_tier ($100 / $200 / $300). Rent paid by
the opponent on each landing is $100 / $200 / $300 by tier respectively
— i.e. ROI per opponent hit is exactly 100% at every tier; you only
profit on the 2nd hit onward.

EXAMPLES (the entire reply — nothing else):
  {"action": "roll_and_move", "player": "robot"}
  {"action": "decide", "choice": "buy"}
  {"action": "decide", "choice": "build_hotel"}

DO NOT reply with text like "I cannot roll dice" — you ARE rolling the dice
by emitting the JSON. The code reads your JSON and tells the arm to act.

DECISION_PENDING CONSTRAINTS (state.decision_pending):
- kind == "utility" (e.g. ELECTRIC_COMPANY, max_tier == 1):
    ONLY "buy" or "skip". build / build_hotel are rejected.
- kind == "property" (BOSTON, SEOUL, TAIPEI, SHANGHAI, TOKYO, BUSAN,
                       NEWYORK, LONDON, max_tier == 3):
    all four choices valid.
- current_tier is your existing tier; build needs current_tier < 2,
  build_hotel needs current_tier < 3.

USER VOICE INTENT (highest priority — overrides everything else):
  The "Context:" line is the user's English speech, transcribed. Map by
  the HEAD NOUN, not exact strings:
    head noun "hotel"  → "build_hotel"   e.g. "Can you buy a hotel?"
    head noun "house"  → "build"         e.g. "Let's build a house."
    bare buy verb or
    head noun "land"   → "buy"           e.g. "Buy it.", "Just the land."
    skip / pass / no   → "skip"          e.g. "Skip it.", "Don't buy."
  "Buy a hotel" / "Buy a house" do NOT map to "buy" — head noun wins.
  If the user's tier is illegal for this decision (hotel/house on a
  utility, or below current_tier), fall back to the closest legal option
  ("buy" for utility; next higher tier when upgrading; else "skip").

ROBOT-TURN DECISIONS (when Context has no explicit user choice):
  There is no fixed heuristic. Look at the full game state — your liquid
  balance, the cost of each option ($100 / $200 / $300 from unowned;
  smaller deltas if you already own a lower tier), the properties you
  already own, the opponent's holdings, the lap count, who's ahead.
  Pick whichever choice (skip / buy / build / build_hotel) you judge best
  for the robot's position. Read the STRATEGIC CONTEXT below before
  defaulting to "buy" — "always land" is a known-weak playstyle here.

STRATEGIC CONTEXT (game-theoretic facts; reason with them, do not treat
as rules):

  GAME LENGTH
  - LAPS_TO_WIN = 5. Avg dice roll = 7 ⇒ ≈ 2 turns per lap ⇒ the winning
    player makes ≈ 10 turns; total game ≈ 20 turns combined.
  - Expected opponent visits to any one tile over the whole game:
    10 / 14 ≈ 0.71  (Poisson λ ≈ 0.71).
  - P(opponent hits a given tile ≥ 2 times) ≈ 16 %.

  TILE ECONOMICS
  - Per-hit ROI is identical at every tier: cost = rent. Break-even at
    1 hit, profit at 2+ hits. So "land is safer per dollar" is a FALSE
    intuition — every tier has the same payback ratio.
  - Looking at single-tile rent EV alone, every purchase is slightly
    negative-EV in this short game. The reasons to buy are not single-
    tile rent EV:

  WHY YOU SHOULD STILL BUY (often aggressively)
  1. Two win paths exist: reach 5 laps first OR bankrupt the opponent.
     Hotels deal $300/hit, which is the fastest way to push the opponent
     toward bankruptcy. Land only deals $100/hit — rarely game-ending.
  2. Asymmetric loss avoidance: if the OPPONENT places hotels and you
     placed only lands, a single hit on their hotel costs you $300 while
     you only ever collect $100 back. To avoid being out-leveraged you
     usually need to match tier intensity.
  3. Denial: an unowned tile becomes the opponent's tile next time they
     land on it. Even a $100 land buy denies a future hotel slot.
  4. Cash held at game end has no extra value (winner is decided by lap
     cap or bankruptcy). Hoarding cash past turn ~7 is wasted utility.

  WHEN CONSERVATIVE PLAY IS RIGHT
  - Late game (own lap_count near 4, or turn_number high): preserve cash
    so you can survive opponent rent and reach lap 5.
  - Low liquid (< $200 after the purchase): one rent hit could bankrupt
    you. Prefer the cheaper tier or skip.
  - Opponent has already built hotels you might land on: keep at least
    $300 buffer.

  WHEN GREEDY PLAY IS RIGHT
  - Early game (lap_count ≤ 1, turn_number low) and liquid ≥ $400.
    Buying a hotel on the first or second arrival is a legitimate
    knockout play in this short game.
  - You're behind in lap_count or assets — high-variance plays are
    correct when you need a swing.
  - The tile is on a high-traffic stretch (e.g. just past GO or after a
    chance tile that frequently sends pieces to it).

  Use these facts to reason about THIS state, then emit ONE choice.

GENERAL RULES:
- Seed money $1000; GO bonus $100 (passing or landing).
- Cumulative tier cost = $100 × tier (land $100, house $200, hotel $300
  total — these are the cumulative purchase prices, not deltas).
- Rent paid by opponent on landing: $100 / $200 / $300 by tier.
- Tax tile $100. Chance: ±$200 coin flip.
- Auto-liquidation: hotels → houses → land if you can't pay.
- 5 laps wins on cap; bankruptcy ends the game immediately.

Reply with ONLY the JSON action. Nothing else.`;

let vlmPlayerInFlight = false;
let vlmPlayerLastTurnKey = null;

// The VLM sees the on-screen rendered game board (background PNG +
// pieces + ownership rectangles, composited into a single JPEG) on every
// inference call. If the canvas capture fails (e.g. tainted by a
// cross-origin asset), we fall back to the physical top-down camera so
// the agent still has *some* visual grounding.
const VLM_PLAYER_FALLBACK_CAMERA = "top";

async function captureBoardImage() {
  try {
    const svg = document.getElementById("pieces");
    if (!svg) return null;
    const vb = (svg.getAttribute("viewBox") || "0 0 1559 794").split(/\s+/).map(Number);
    const w = vb[2] || 1559;
    const h = vb[3] || 794;

    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);

    // Background board image (same-origin under /assets).
    const bgImg = document.querySelector("#board-host img");
    if (bgImg) {
      if (!(bgImg.complete && bgImg.naturalWidth > 0)) {
        await new Promise((res, rej) => {
          bgImg.addEventListener("load", res, { once: true });
          bgImg.addEventListener("error", rej, { once: true });
        });
      }
      ctx.drawImage(bgImg, 0, 0, w, h);
    }

    // Clone the SVG and inject a <style> resolving var(--user)/var(--robot)
    // — standalone SVG images don't inherit the page's CSS variables.
    const cloned = svg.cloneNode(true);
    cloned.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const cs = getComputedStyle(document.documentElement);
    const userCol = (cs.getPropertyValue("--user") || "#EF5350").trim();
    const robotCol = (cs.getPropertyValue("--robot") || "#2E7D32").trim();
    const styleEl = document.createElementNS("http://www.w3.org/2000/svg", "style");
    styleEl.textContent =
      `:root { --user: ${userCol}; --robot: ${robotCol}; } ` +
      `* { --user: ${userCol}; --robot: ${robotCol}; }`;
    cloned.insertBefore(styleEl, cloned.firstChild);

    const svgStr = new XMLSerializer().serializeToString(cloned);
    const svgBlob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    try {
      await new Promise((res, rej) => {
        const overlay = new Image();
        overlay.onload = () => { ctx.drawImage(overlay, 0, 0, w, h); res(); };
        overlay.onerror = rej;
        overlay.src = url;
      });
    } finally {
      URL.revokeObjectURL(url);
    }

    // toDataURL returns "data:image/jpeg;base64,...". The orchestrator
    // wants the bare base64 payload, so strip the prefix.
    return canvas.toDataURL("image/jpeg", 0.8).split(",")[1] || null;
  } catch (err) {
    console.warn("[vlm-player] captureBoardImage failed:", err);
    return null;
  }
}

async function vlmInferRaw(prompt) {
  const image_b64 = await captureBoardImage();
  const body = image_b64
    ? { camera: "none", image_b64, prompt, client: "robopoly" }
    : { camera: VLM_PLAYER_FALLBACK_CAMERA, prompt, client: "robopoly" };
  const r = await fetch(`${VLM_BASE}/api/vlm/infer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${r.status}`);
  }
  const respBody = await r.json();
  return respBody.response || "";
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
    const max = pendingDecision.max_tier ?? 3;
    summary.decision_pending = {
      property_id: pendingDecision.property_id,
      current_tier: pendingDecision.current_tier ?? 0,
      max_tier: max,
      // Explicit kind so the model doesn't have to infer "is this a
      // utility?" from max_tier == 1. "utility" → only buy/skip valid.
      kind: pendingDecision.card?.kind ?? (max === 1 ? "utility" : "property"),
    };
  }
  return summary;
}

async function executeVlmAction(action) {
  if (!action || typeof action !== "object") {
    console.warn("[vlm-player] executeVlmAction: not an object:", action);
    return false;
  }
  if (action.action === "roll_and_move") {
    // Reuse the existing Roll-dice chain — it handles roll, physical move,
    // tile resolution, auto-rent, auto-jail PnP, and auto end-turn.
    const btn = document.getElementById("btn-roll-dice");
    if (!btn) {
      console.warn("[vlm-player] executeVlmAction: btn-roll-dice not in DOM");
      return false;
    }
    if (btn.disabled) {
      // The most common silent dead-end: turnInFlight stuck true from a
      // prior failed chain, fsm not TURN_START, or winner already declared.
      // Surface the exact reason so the operator can see why nothing moved.
      console.warn(
        "[vlm-player] executeVlmAction: btn-roll-dice is disabled — action dropped.",
        { fsm: currentState && currentState.fsm,
          turn: currentState && currentState.turn,
          winner: currentState && currentState.winner,
          turnInFlight,
        },
      );
      return false;
    }
    console.log("[vlm-player] dispatching roll_and_move via btn-roll-dice click");
    btn.click();
    return true;
  }
  if (action.action === "decide") {
    const c = action.choice;
    if (c === "build") { await submitDecision("build", 1); return true; }
    if (["skip", "buy", "build_hotel"].includes(c)) {
      await submitDecision(c);
      return true;
    }
    console.warn("[vlm-player] executeVlmAction: unknown decide choice:", c);
    return false;
  }
  console.warn("[vlm-player] executeVlmAction: unknown action:", action.action);
  return false;
}

// Always inline the action grammar in the user message too, so the model
// can't drift into a "vision assistant, I cannot roll dice" refusal even if
// the per-client system prompt got overridden somewhere upstream.
// Per-request guard. The full mapping rules and STRATEGIC CONTEXT live
// in the system prompt; this short block just keeps the JSON output
// shape and the max_tier guard front-of-mind in case the system prompt
// was overridden upstream.
const VLM_PLAYER_INLINE_RULES = `Reply with ONE JSON object. No prose, no fences.
Valid replies:
  {"action":"roll_and_move","player":"user"|"robot"}   (when fsm=="TURN_START")
  {"action":"decide","choice":"skip"|"buy"|"build"|"build_hotel"}  (when state.decision_pending)
Honor the user's voice intent in Context (head-noun: hotel→build_hotel,
house→build, land/bare-buy→buy, skip/pass/no→skip). If decision_pending.kind
== "utility" only "buy" or "skip" are legal — never emit build/build_hotel
there. See the system prompt for the full STRATEGIC CONTEXT.`;

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
    vlmPlayerAct(
      "You (robot) landed on a buyable property. There is no human voice " +
      "intent for this decision — read the State JSON AND the STRATEGIC " +
      "CONTEXT in the system prompt before choosing. In this 5-lap game " +
      "'always buy land' is a weak default; consider build / build_hotel " +
      "when you can afford them, especially in the early game. Respect " +
      "decision_pending.max_tier (utility tiles allow only buy or skip). " +
      "Output exactly one of: skip / buy / build / build_hotel.",
    );
  }
}

async function fetchGameRulesSpec() {
  // Pull the authoritative spec (doc/game_logic.md) from the robopoly
  // backend so any future spec edit auto-propagates into the agent's
  // system prompt. Returns "" if the endpoint isn't available (older
  // server, stripped image, etc.); the caller falls back to the
  // hard-coded rules summary in VLM_PLAYER_SYSTEM_PROMPT.
  try {
    const r = await fetch("/api/game/rules");
    if (!r.ok) return "";
    return await r.text();
  } catch (err) {
    console.warn("[vlm-player] fetch rules spec failed:", err);
    return "";
  }
}

async function ensureVlmPlayerSystemPrompt() {
  // Install the agent prompt on boot so a leftover vision-assistant
  // prompt can't make the VLM refuse with "I cannot physically roll
  // dice for you" instead of emitting JSON.
  //
  // We deliberately do NOT append doc/game_logic.md anymore — the
  // VLM_PLAYER_SYSTEM_PROMPT already contains the rules the agent
  // actually uses (costs, rent, lap cap, decision constraints). The
  // 270-line spec was ~3000 extra tokens per call with little payoff.
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

// ==== Robot-state stream (localhost:8000 WS) ===============================
// Three persistent WebSockets feed the X-hotkey Q&A path with the latest
// joint angles + EEF cartesian pose. We just cache the most recent frame
// from each socket — no polling, no re-fetch on hotkey press.

const robotState = { eef_pose: null, eef_rpy: null, joint_states: null };

function setupRobotStateStream() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  // VLM_HOST = "<hostname>:8000" — the orchestrator hosting the joint /
  // EEF topics (see movensys_vlm/router.py /api/stream/*).
  const base = `${proto}//${VLM_HOST}`;
  const subs = [
    { path: "/api/stream/eef_pose", key: "eef_pose" },
    { path: "/api/stream/eef_rpy", key: "eef_rpy" },
    { path: "/api/stream/joint_states", key: "joint_states" },
  ];
  for (const s of subs) connectRobotWs(base + s.path, s.key);
}

function connectRobotWs(url, key) {
  let backoff = 1000;
  const open = () => {
    let ws;
    try { ws = new WebSocket(url); }
    catch { setTimeout(open, backoff); backoff = Math.min(backoff * 2, 10000); return; }
    ws.onopen = () => { backoff = 1000; };
    ws.onmessage = (ev) => {
      try {
        const env = JSON.parse(ev.data);
        if (env && env.error == null && env.data != null) robotState[key] = env.data;
      } catch { /* drop malformed frame */ }
    };
    ws.onerror = () => { try { ws.close(); } catch {} };
    ws.onclose = () => {
      setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 10000);
    };
  };
  open();
}

function snapshotRobotState() {
  // Trim noisy fields so the prompt stays compact. We keep the
  // human-meaningful joint angles + xyz/rpy and drop covariances /
  // raw header buffers that are never used by the VLM.
  const out = {};
  const js = robotState.joint_states;
  if (js && Array.isArray(js.name) && Array.isArray(js.position)) {
    const joints = {};
    js.name.forEach((n, i) => { joints[n] = Number((js.position[i] ?? 0).toFixed(4)); });
    out.joint_positions_rad = joints;
  }
  const ep = robotState.eef_pose;
  if (ep && ep.position) {
    out.eef_pose_m = {
      x: Number((ep.position.x ?? 0).toFixed(4)),
      y: Number((ep.position.y ?? 0).toFixed(4)),
      z: Number((ep.position.z ?? 0).toFixed(4)),
    };
    if (ep.orientation) {
      out.eef_quat = {
        x: Number((ep.orientation.x ?? 0).toFixed(4)),
        y: Number((ep.orientation.y ?? 0).toFixed(4)),
        z: Number((ep.orientation.z ?? 0).toFixed(4)),
        w: Number((ep.orientation.w ?? 0).toFixed(4)),
      };
    }
  }
  const er = robotState.eef_rpy;
  if (er && er.vector) {
    out.eef_rpy_rad = {
      roll: Number((er.vector.x ?? 0).toFixed(4)),
      pitch: Number((er.vector.y ?? 0).toFixed(4)),
      yaw: Number((er.vector.z ?? 0).toFixed(4)),
    };
  }
  return Object.keys(out).length ? out : null;
}

// ==== Push-to-talk hotkeys (Z = act, X = ask) ==============================
// One shared MediaRecorder bay reused by both keys — only one capture can
// be in flight at a time. We re-acquire the mic stream per press so the
// user can swap mic devices through the existing dropdown without
// reloading the page.

const HOTKEY = { ACT: "z", ASK: "x" };
let hotkeyState = "idle";        // "idle" | "armed" | "recording" | "busy"
let hotkeyMode = null;            // "act" | "ask"
let hotkeyRecorder = null;
let hotkeyChunks = [];
let hotkeyStream = null;

function setHotkeyKbd(mode, active) {
  // Mirror the press state into two indicators:
  //   1. The pills next to "idle" in the Ask VLM header (always present).
  //   2. The <kbd>Z</kbd>/<kbd>X</kbd> tokens in the legend under the
  //      Query & response title (only present if the hint row is in the DOM).
  const zPill = document.getElementById("hotkey-pill-z");
  const xPill = document.getElementById("hotkey-pill-x");
  if (zPill) zPill.classList.toggle("live", !!(active && mode === "act"));
  if (xPill) xPill.classList.toggle("live", !!(active && mode === "ask"));

  const root = document.querySelector(".vlm-hotkey-hint");
  if (root) {
    const tokens = root.querySelectorAll("kbd");
    tokens.forEach((k) => k.classList.remove("live"));
    if (active) {
      const target = mode === "act" ? "Z" : "X";
      tokens.forEach((k) => { if (k.textContent.trim() === target) k.classList.add("live"); });
    }
  }
}

async function hotkeyStartRecording(mode) {
  if (hotkeyState !== "idle") return;
  hotkeyState = "armed";
  hotkeyMode = mode;
  setHotkeyState(`${mode === "act" ? "Z" : "X"} — listening…`);
  setHotkeyKbd(mode, true);
  if (!navigator.mediaDevices?.getUserMedia) {
    setHotkeyState("mic not available", true);
    hotkeyState = "idle"; hotkeyMode = null; setHotkeyKbd(null, false);
    return;
  }
  try {
    const micSelect = document.getElementById("vlm-mic-device");
    const deviceId = micSelect ? micSelect.value : "";
    const constraints = { audio: deviceId ? { deviceId: { exact: deviceId } } : true };
    hotkeyStream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch (err) {
    setHotkeyState(`mic denied: ${err.name || err}`, true);
    hotkeyState = "idle"; hotkeyMode = null; setHotkeyKbd(null, false);
    return;
  }
  // If the user released the key before permission resolved, abandon the
  // capture instead of starting a recording the user never asked for.
  if (hotkeyState !== "armed") {
    hotkeyStream.getTracks().forEach((t) => t.stop());
    hotkeyStream = null;
    return;
  }
  hotkeyChunks = [];
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : (MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "");
  hotkeyRecorder = mime ? new MediaRecorder(hotkeyStream, { mimeType: mime })
                        : new MediaRecorder(hotkeyStream);
  hotkeyRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) hotkeyChunks.push(e.data);
  };
  hotkeyRecorder.onstop = onHotkeyRecorderStop;
  hotkeyRecorder.start();
  hotkeyState = "recording";
}

function hotkeyStopRecording() {
  if (hotkeyState === "armed") {
    // The mic stream was still being negotiated — flip state so the
    // pending getUserMedia resolver tears down before MediaRecorder starts.
    hotkeyState = "idle";
    setHotkeyState("");
    setHotkeyKbd(null, false);
    return;
  }
  if (hotkeyState !== "recording") return;
  hotkeyState = "busy";
  setHotkeyState(`${hotkeyMode === "act" ? "Z" : "X"} — transcribing…`);
  try { hotkeyRecorder.stop(); }
  catch (err) { console.warn("[hotkey] stop:", err); resetHotkey(); }
}

function resetHotkey() {
  if (hotkeyStream) hotkeyStream.getTracks().forEach((t) => t.stop());
  hotkeyStream = null;
  hotkeyRecorder = null;
  hotkeyChunks = [];
  hotkeyState = "idle";
  hotkeyMode = null;
  setHotkeyKbd(null, false);
}

async function onHotkeyRecorderStop() {
  const mode = hotkeyMode;
  const chunks = hotkeyChunks;
  const recMime = hotkeyRecorder ? hotkeyRecorder.mimeType : "audio/webm";
  if (hotkeyStream) hotkeyStream.getTracks().forEach((t) => t.stop());
  hotkeyStream = null;
  hotkeyRecorder = null;
  hotkeyChunks = [];

  setHotkeyKbd(null, false);
  if (!chunks.length) {
    setHotkeyState("no audio captured", true);
    appendChat({ role: "sys", text: "Heard nothing — hold the key longer." });
    hotkeyState = "idle"; hotkeyMode = null;
    return;
  }
  const blob = new Blob(chunks, { type: recMime || "audio/webm" });

  let text = "";
  try {
    text = await whisperTranscribe(blob);
  } catch (err) {
    appendChat({ role: "sys", text: `STT failed: ${err}` });
    setHotkeyState(`stt failed: ${err}`, true);
    hotkeyState = "idle"; hotkeyMode = null;
    return;
  }
  text = (text || "").trim();
  if (!text) {
    appendChat({ role: "sys", text: "Heard nothing — try again." });
    setHotkeyState("empty transcript", true);
    hotkeyState = "idle"; hotkeyMode = null;
    return;
  }
  appendChat({ role: "me", text });
  setHotkeyState("");

  try {
    if (mode === "act"
        && document.body.classList.contains("game-mode")
        && isStateInquiry(text)) {
      flashCurrentStateOverlay();
      appendChat({ role: "sys", text: "(showing board state)" });
    } else if (mode === "act") {
      await dispatchVoiceAction(text);
    } else {
      await askVlmAboutState(text);
    }
  } catch (err) {
    appendChat({ role: "bot", text: String(err), error: true });
  } finally {
    hotkeyState = "idle";
    hotkeyMode = null;
  }
}

// Whisper is asked to transcribe in English only. The strings below are
// the most common hallucinations Whisper emits when the audio is silence
// or background hum — we drop them so the agent never sees a phantom
// "Thank you." that wasn't actually spoken.
const WHISPER_HALLUCINATIONS = new Set([
  "thank you", "thank you.", "thank you!",
  "thanks for watching", "thanks for watching.", "thanks for watching!",
  "thank you for watching", "thank you for watching.",
  "you", "you.", ".", "..", "...",
  "subscribe", "subscribe.",
  "[music]", "[applause]", "[silence]",
  "bye", "bye.",
]);
function isWhisperHallucination(text) {
  const clean = (text || "").trim().toLowerCase().replace(/\s+/g, " ");
  return clean === "" || WHISPER_HALLUCINATIONS.has(clean);
}
async function whisperTranscribe(blob) {
  const form = new FormData();
  const ext = blob.type.includes("webm") ? "webm"
            : blob.type.includes("ogg")  ? "ogg"
            : blob.type.includes("mp4")  ? "mp4"
            : "wav";
  form.append("file", blob, `mic.${ext}`);
  form.append("language", "en");
  const r = await fetch(`${VLM_BASE}/api/whisper/transcribe`, { method: "POST", body: form });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const j = await r.json(); if (j.detail) detail = j.detail; } catch {}
    throw new Error(detail);
  }
  const body = await r.json();
  if (body.error) throw new Error(body.error);
  const raw = body.text || "";
  return isWhisperHallucination(raw) ? "" : raw;
}

async function dispatchVoiceAction(text) {
  // Z-key: route the transcript through the existing VLM-player agent.
  // It already handles TURN_START (roll+move) and AWAIT_DECISION (decide).
  if (!currentState) {
    appendChat({ role: "sys", text: "No game state yet — ignored." });
    return;
  }
  if (currentState.winner) {
    appendChat({ role: "sys", text: "Game is over — ignored." });
    return;
  }
  const fsm = currentState.fsm;
  if (fsm !== "TURN_START" && fsm !== "AWAIT_DECISION") {
    appendChat({ role: "sys", text: `Ignored — wrong phase (${fsm}).` });
    return;
  }
  if (fsm === "TURN_START" && currentState.turn !== "user") {
    appendChat({ role: "sys", text: "Not your turn — wait for the robot." });
    return;
  }
  const pending = appendChat({ role: "bot", text: "Dispatching action…", pending: true });
  try {
    await vlmPlayerAct(text);
    updateChatMsg(pending, {
      text: fsm === "AWAIT_DECISION" ? "(decision sent)" : "(turn dispatched)",
      meta: new Date().toLocaleTimeString(),
    });
  } catch (err) {
    updateChatMsg(pending, { text: String(err), error: true });
  }
}

// X-key: contextual Q&A. The transcript becomes a question; we attach the
// current game-state JSON + the latest robot snapshot from the WS cache.
const VLM_QA_SYSTEM_PROMPT = `You are a helpful, concise assistant for a Movensys-Monopoly demo.
The user may ask about:
  - the current state of the 6-DOF arm (joint angles in radians, EEF cartesian pose in metres)
  - the current game state, including why certain property decisions were made

Answer in plain prose. No JSON, no code fences, no markdown headings. Keep it
to 1–4 sentences when possible. If the user asks WHY a particular property
buy/skip/build choice was made, ground your reasoning in the JSON game state
(liquid cash, owned properties and their tiers, distance to opponent's
holdings, lap count, fsm phase). If the robot pose / joint fields are
missing, say so briefly rather than inventing values.`;

let vlmQaPromptInstalled = false;
async function ensureVlmQaSystemPrompt() {
  if (vlmQaPromptInstalled) return;
  try {
    await fetch(`${VLM_BASE}/api/vlm/system_prompt?client=robopoly_qa`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: VLM_QA_SYSTEM_PROMPT }),
    });
    vlmQaPromptInstalled = true;
  } catch (err) {
    console.warn("[vlm-qa] system prompt install failed:", err);
  }
}

async function askVlmAboutState(question) {
  await ensureVlmQaSystemPrompt();
  const summary = currentState ? buildVlmStateSummary(currentState) : null;
  const robot = snapshotRobotState();
  const prompt =
    `User question: ${question}\n\n` +
    `Game state JSON (current):\n${JSON.stringify(summary, null, 2)}\n\n` +
    `Robot state (latest from joint_states / eef_pose WS):\n` +
    `${robot ? JSON.stringify(robot, null, 2) : "(no robot telemetry available)"}\n\n` +
    `Answer the user. Plain prose, 1–4 sentences.`;
  const pending = appendChat({ role: "bot", text: "Thinking…", pending: true });
  const started = performance.now();
  try {
    const r = await fetch(`${VLM_BASE}/api/vlm/infer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        camera: "none",
        prompt,
        client: "robopoly_qa",
        max_tokens: 512,
        temperature: 0.4,
      }),
    });
    const body = await r.json();
    const elapsedMs = Math.round(performance.now() - started);
    if (!r.ok) {
      updateChatMsg(pending, {
        text: body.detail || `HTTP ${r.status}`,
        meta: `${elapsedMs} ms`,
        error: true,
      });
      return;
    }
    updateChatMsg(pending, {
      text: body.response || "(empty response)",
      meta: `${elapsedMs} ms · ${new Date().toLocaleTimeString()}`,
    });
  } catch (err) {
    updateChatMsg(pending, { text: String(err), error: true });
  }
}

function isTypingTarget(el) {
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function setupHotkeys() {
  document.addEventListener("keydown", (e) => {
    if (e.repeat) return;
    if (document.hidden) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (isTypingTarget(e.target)) return;
    const k = e.key.toLowerCase();
    if (k === "escape") { closeChatOverlay(); return; }

    const isGame = document.body.classList.contains("game-mode");
    // Game mode: C reveals/hides the overlay without recording. Z/X always
    // act as hold-to-record hotkeys *and* additionally open the overlay
    // so the operator can see the transcript while talking.
    if (isGame && k === "c") { e.preventDefault(); toggleChatOverlay(); return; }
    if (k === HOTKEY.ACT) {
      e.preventDefault();
      if (isGame) maybeOpenChatOverlay();
      hotkeyStartRecording("act");
      return;
    }
    if (k === HOTKEY.ASK) {
      e.preventDefault();
      if (isGame) maybeOpenChatOverlay();
      hotkeyStartRecording("ask");
      return;
    }
  });
  document.addEventListener("keyup", (e) => {
    const k = e.key.toLowerCase();
    if (k === HOTKEY.ACT && hotkeyMode === "act") { e.preventDefault(); hotkeyStopRecording(); return; }
    if (k === HOTKEY.ASK && hotkeyMode === "ask") { e.preventDefault(); hotkeyStopRecording(); return; }
  });
  // If the user tabs out mid-press, drop the recording so we don't ship
  // half-captured audio when they come back.
  window.addEventListener("blur", () => {
    if (hotkeyState === "recording" || hotkeyState === "armed") hotkeyStopRecording();
  });
}

// ---- mode toggle (Debug ↔ Game) -------------------------------------------

async function resetGame() {
  turnInFlight = false;
  vlmPlayerLastTurnKey = null;
  const chat = chatEl();
  if (chat) chat.replaceChildren();
  // System prompt slot is separate from the vector-DB memory, but a
  // different client (or an orchestrator restart) could have replaced it.
  // Re-install on every reset so the game always starts with the known
  // agent prompt. PUT is cheap — a single short text payload.
  await ensureVlmPlayerSystemPrompt();
  try {
    await fetch(`${VLM_BASE}/api/vlm/memory`, { method: "DELETE" });
  } catch (err) {
    console.warn("reset: clear vlm memory failed", err);
  }
  await postJson("/api/game/start", { board: "final" });
  await loadBoardVisual("final");
  await refreshState();
}

function applyMode(mode) {
  const isGame = mode === "game";
  document.body.classList.toggle("game-mode", isGame);
  document.body.classList.toggle("debug-mode", !isGame);
  const btn = document.getElementById("mode-toggle");
  if (btn) btn.textContent = isGame ? "Debug Mode" : "Game Mode";
}

function setupModeToggle() {
  const params = new URLSearchParams(location.search);
  const initial = params.get("mode") === "game" ? "game" : "debug";
  applyMode(initial);
  if (initial === "game") {
    resetGame().catch((err) => console.warn("reset on game-mode entry failed", err));
  }
  const btn = document.getElementById("mode-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const cur = document.body.classList.contains("game-mode") ? "game" : "debug";
    const next = cur === "game" ? "debug" : "game";
    const url = new URL(location.href);
    if (next === "game") url.searchParams.set("mode", "game");
    else url.searchParams.delete("mode");
    history.replaceState(null, "", url.toString());
    applyMode(next);
    if (next === "game") {
      resetGame().catch((err) => console.warn("reset on toggle to game failed", err));
    }
  });
}

// ---- boot -----------------------------------------------------------------

(async () => {
  await loadBadges();
  await loadBoardVisual("final");
  setupOwnershipRects();
  setupPieceDragging();
  setupModeToggle();
  renderYoloStatus();
  await refreshState();
  openStream();
  setupVlm();
  setupRobotStateStream();
  setupHotkeys();
  await ensureVlmPlayerSystemPrompt();
  // First call after we have a snapshot — kicks the robot if the saved
  // state already has turn=robot on load.
  maybeAutoTriggerRobotTurn();
})();
