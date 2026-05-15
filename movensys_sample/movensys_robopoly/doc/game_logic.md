# Game logic

This is the authoritative spec for the robopoly gameplay loop. Where the
spec and the current code disagree, the spec wins — flagged items at the
end are TODOs against the implementation, not contradictions.

## 1. Players

1.1. There are 2 players: **user** (red cube) and **robot** (green cube).
1.2. The first turn is the user's. Then turns alternate user → robot → user → …
1.3. All interactions go through buttons on http://localhost:7999/. No
     keyboard shortcuts or text commands are required.

## 2. Money

2.1. Each player has two figures shown in the UI:
    2.1.1. **Liquid** — cash on hand. Starts at **$1000** for both
           players (board JSON `seed_money`). All buys, builds, rents,
           taxes, and chance payouts move this number.
    2.1.2. **Assets** — total value of owned tiers (sum of $100 / $200
           / $300 across all owned properties). Recomputed from the
           property state, not stored separately.
2.2. Passing GO grants a **start bonus** of $100 (board JSON
     `start_bonus`).
2.3. A player is bankrupt when their liquid would go negative and they
     have no assets left to sell. On bankruptcy the other player wins.

## 3. Turn flow (same for both players)

A turn is driven by a **single button — *Roll dice*** — that chains
roll → move → tile resolution → end-turn automatically. The only
human interruption is the property-buy modal (§4.1.1 / §4.1.2); rent,
tax, chance, and auto-liquidation all resolve server-side without
prompting.

3.1. **Roll the dice** — clicking *Roll dice* runs the YOLO robot
     pipeline:
    3.1.1. The arm picks the dice and drops it in the rolling area
           (`pick_and_place.py dice GO`).
    3.1.2. The YOLO dice detector publishes the face value on
           `/yolo_dice_detector/dice_number`, which the server reads
           via the orchestrator's `/api/topics/dice_number`.
    3.1.3. The detected value is submitted as the current player's
           dice roll.
3.2. **Move (automatic)** — immediately after the dice value is
     submitted, the client drives the player's cube to the computed
     destination via `/api/move/apply_robot` (subprocess
     `pick_and_place.py <cube> <board_pos>`). The on-screen piece
     advances at the same moment.
3.3. **Resolve the tile (automatic)** — runs server-side as part of
     the move (see §4):
    3.3.1. Property arrival on an unowned tile, or a self-owned tile
           with an available upgrade, pops the **Buy modal** (the only
           place the chain pauses for human input).
    3.3.2. Rent owed to the opponent is paid automatically. If the
           payer cannot cover the rent, the auto-liquidation pathway
           in §5.2 runs first; if still short, the payer goes
           bankrupt and the opponent wins.
    3.3.3. Tax and chance cash deltas apply automatically; shortfalls
           run the same auto-liquidation pathway.
3.4. **End turn (automatic)** — control flips to the other player
     as soon as the tile resolution completes (or, when the Buy
     modal was shown, as soon as the player's choice is submitted).
     There is no *End turn* button.

## 4. Arrival actions by tile kind

### 4.1 Property tile (Suwon, Seoul, Jeonju, Daejeon, Gyeongju, Busan, Daegu, Bundang)

All properties use a **uniform pricing scheme**, independent of which
tile it is:

| Tier  | Cost    | Visual on the board |
|-------|---------|---------------------|
| Land  | **$100** | 1 colored circle    |
| House | **$200** | 2 colored circles   |
| Hotel | **$300** | 3 colored circles   |

Red circles = user-owned, green = robot.

4.1.1. **Unowned tile** — the player picks any tier to buy directly
       (free choice). The Buy modal offers *Skip / Buy land / Buy +
       house / Buy + hotel*.
4.1.2. **Already owned by the current player** — the modal offers the
       upgrade path. The "delta" cost = $100 per tier crossed.
    4.1.2.1. Land → House: pay $100.
    4.1.2.2. House → Hotel: pay $100.
    4.1.2.3. Land → Hotel (skip house): pay $200.
    4.1.2.4. Hotel → nothing more to buy.
4.1.3. **Already owned by the opponent** — the current player **pays
       rent** to the opponent and cannot buy. Rent equals the **total
       price the opponent has paid in** for the current tier (i.e.
       the cumulative buy cost from §4.1):
    4.1.3.1. Opponent owns land    → rent = **$100**.
    4.1.3.2. Opponent owns house   → rent = **$200**.
    4.1.3.3. Opponent owns hotel   → rent = **$300**.
4.1.4. If the rent payment would bankrupt the payer, the game
       auto-liquidates assets first (sell buildings, then mortgage
       land). If still short, the payer goes bankrupt and the opponent
       wins.

### 4.2 Utility tile (Electric Company)

4.2.1. Buyable for $100 (land tier only — no houses or hotels on
       utilities).
4.2.2. Rent if owned by the opponent = **$100** (flat, same as the
       land-tier rent in §4.1.3.1; the dice sum does not factor in).

### 4.3 Tax tile (Non-Free Parking)

4.3.1. Landing pays a flat **$100** to the bank. (The tile's
       `amount` field in the board JSON is no longer used.)
       Auto-liquidation rules in §4.1.4 apply on shortfall.

### 4.4 Chance tile

4.4.1. Drawing a card yields either **+$200** or **−$200** (from/to
       the bank, equal probability).
4.4.2. No other effects (no jail-card draws, no move-to-tile cards) —
       chance in this game is a coin flip of cash only.

### 4.5 Go-to-jail tile

4.5.1. The player's piece is teleported to the **IN_JAIL** tile
       immediately. Their turn ends. robot arm need pick and place automatically for this.
4.5.2. While in jail, the player must either:
    4.5.2.1. Roll **6** on their next turn (any face counts — single
             die) to escape and move 6 spaces from IN_JAIL, **or**
    4.5.2.2. Wait out **2 turns** in jail. On the third turn after
             being jailed they are released automatically and roll
             normally.
4.5.3. Properties owned during jail still collect rent from the
       opponent.

### 4.6 GO tile / IN_JAIL tile (jail visit, not jailed) / blank tiles

4.6.1. The GO start bonus is granted whether the player **passes**
       GO or **lands** on it. IN_JAIL (as a visitor, not jailed) and
       blank tiles have no arrival effect.

## 5. Out-of-money handling

5.1. **No voluntary selling.** A player cannot choose to sell or
     downgrade their own properties during normal play. Owned tiers
     can only move down via the auto-liquidation pathway below.
5.2. **Auto-liquidation** kicks in only when the player owes a
     payment (rent §4.1.3, utility rent §4.2.2, tax §4.3, chance loss
     §4.4) that their current liquid cannot cover. It runs in this
     fixed order until the debt is paid:
    5.2.1. Downgrade hotels to houses (refund $100 each, leaves 2
           circles).
    5.2.2. Downgrade houses to land (refund $100 each, leaves 1
           circle).
    5.2.3. Sell remaining land $100.
    5.2.4. If the debt is still not covered after step 5.2.3, the
           player is **bankrupt** and the opponent wins per §6.1.
5.3. Auto-liquidation is the only way a player's circle count
     decreases. There is just one "sell" event — each tier drop
     (hotel→house, house→land, or land→unowned) emits the same
     `tier_sold` event, surfaced in the notification banner as
     "user sold hotel on Seoul (+$100)" etc. No separate
     `mortgage` / `building_sold` distinction.

## 6. Win condition

The game ends as soon as **either** of these triggers:

6.1. **Bankruptcy.** A player can no longer pay what they owe even
     after auto-liquidation. The other player wins immediately.
6.2. **Lap limit.** A player has completed **5 full rotations of the
     board** (= passed GO 5 times). Tracked per player by counting
     `lap_completed` events. As soon as either player's counter
     reaches 5, the game ends at the end of that turn.
    6.2.1. Winner = the player with the larger **accumulated
           money** = `liquid + assets value`. Assets value uses the
           same §2.1.2 sum ($100 × land tiers + $200 × house tiers
           + $300 × hotel tiers).
    6.2.2. If both totals are equal the UI banner shows **"draw"**.
    6.2.3. The 5-lap counter and bankruptcy condition are checked
           independently — bankruptcy still ends the game
           immediately, even before any player reaches 5 laps.

There is no other end condition — no "first to N dollars" and no
fixed cash threshold.

## 7. UI surfaces relevant to gameplay

7.1. **Game board** in the center, with the live cube positions and
     ownership circles overlay.
7.2. **Game state card** (top-right): turn, last dice, both positions,
     `is_YOLO` toggle, save/load buttons.
7.3. **Dice Status card**: dice face + two buttons — **Roll dice**
     (drives the full §3 chain) and **Reset game** (restart the
     current board from turn 1). The previous *Apply move* and
     *End turn* buttons are removed; both actions are automatic.
7.4. **Events** card: raw event log (debugging).
7.5. **Notification banner** under the board: human-readable
     announcements ("It's robot's turn", "robot bought Seoul", "user
     paid rent ($100)", "🏆 user wins!").
7.6. **Money chips** under the board: user / robot liquid balances
     (large monospace value, color-flashed on change).
7.7. **Ask VLM** sidebar (left): unrelated to gameplay rules — it's a
     debug / interaction surface for the vision-language model.

## 8. Save / load

8.1. *SAVE* / *LOAD* buttons in the Game State card persist the
     current snapshot to `saved_status.yaml` next to the server. Loading
     replaces the entire game state. Memory in the vector DB is not
     part of the save.

---

## Appendix — implementation notes

All spec items above are now in code. Key locations:

- Constants live at the top of `game/rules.py`:
  `TIER_PRICE` / `LAND_PRICE` / `HOUSE_PRICE` / `HOTEL_PRICE` /
  `TAX_AMOUNT` / `CHANCE_AMOUNT` / `LAPS_TO_WIN`.
- `tier_of(p)` + `_set_tier(p, target)` collapse the
  `houses` / `has_hotel` representation into a 0–3 tier integer.
- `assets_value(state, player)` and `total_money(state, player)` are
  the spec §2.1.2 / §6.2.1 helpers. The frontend computes the same
  totals client-side from `state.properties`.
- `rules.sell_tier()` is the only sell path; `_auto_liquidate` walks
  tier 3 → 2 → 1 and emits one `tier_sold` event per drop.
- Chance (§4.4) is a `random.choice([+200, -200])` inline in
  `_resolve_once`. `chance.json` is kept as documentation only.
- Jail (§4.5) is set up by `effects.go_to_jail` (`in_jail = True`,
  `jail_turns_left = 2`); `submit_dice` enforces "roll 6 to escape
  or skip a turn", emits `jail_escaped` / `jail_skipped` /
  `jail_released`.
- Lap cap (§6.2) lives in `rules.end_turn` — checks
  `lap_count[p] >= LAPS_TO_WIN`, computes totals, sets
  `state.winner` (or `None` on a tie). Manager publishes `game_won`
  with `{winner, draw, reason: "lap_cap", totals}`.
- The voluntary mortgage / unmortgage / sell_building HTTP routes
  are deleted; the manager helpers are also gone.
- Per-tile `price_buy` / `price_building` / `rent_table` / `amount`
  fields in `static/assets/boards/board_final.json` are silently
  ignored by the Pydantic model; cosmetic deletion only.
