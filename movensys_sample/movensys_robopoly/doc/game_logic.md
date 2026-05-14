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

3.1. **Roll the dice** — clicking *Roll dice* runs the YOLO robot
     pipeline:
    3.1.1. The arm picks the dice and drops it in the rolling area
           (`pick_and_place.py dice GO`).
    3.1.2. The YOLO dice detector publishes the face value on
           `/yolo_dice_detector/dice_number`, which the server reads
           via the orchestrator's `/api/topics/dice_number`.
    3.1.3. The detected value is submitted as the current player's
           dice roll.
3.2. **Move** — clicking *Apply move* drives the player's cube to the
     new tile via the orchestrator's `/api/move/*` endpoints (subprocess
     `pick_and_place.py <cube> <board_pos>`). The on-screen piece
     advances at the same moment.
3.3. **Resolve the tile** — depends on the kind of tile landed on
     (see §4).
3.4. **End turn** — *End turn* button hands control to the other
     player. Disabled until the tile has been resolved (or the player
     is bankrupt).

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
       rent** to the opponent and cannot buy. Rent comes from the
       tile's `rent_table` indexed by the tier owned by the opponent:
    4.1.3.1. Land (`houses=0, !hotel`)  → `rent_table[0]`.
    4.1.3.2. House (`houses≥1, !hotel`) → `rent_table[1]`.
    4.1.3.3. Hotel                       → `rent_table[5]` (last entry).
4.1.4. If the rent payment would bankrupt the payer, the game
       auto-liquidates assets first (sell buildings, then mortgage
       land). If still short, the payer goes bankrupt and the opponent
       wins.

### 4.2 Utility tile (Electric Company)

4.2.1. Buyable for $100 (land tier only — no houses or hotels on
       utilities).
4.2.2. Rent if owned by the opponent = `dice_sum × 4`.

### 4.3 Tax tile (Non-Free Parking)

4.3.1. Landing pays a fixed amount to the bank (the tile's `amount`
       in the board JSON). Auto-liquidation rules apply on shortfall.

### 4.4 Chance tile

4.4.1. Drawing a card yields either **+$100** or **−$100** (from/to
       the bank, equal probability).
4.4.2. No other effects (no jail-card draws, no move-to-tile cards) —
       chance in this game is a coin flip of cash only.

### 4.5 Go-to-jail tile

4.5.1. The player's piece is teleported to the **IN_JAIL** tile
       immediately. Their turn ends.
4.5.2. While in jail, the player must either:
    4.5.2.1. Roll **6** on their next turn (any face counts — single
             die) to escape and move 6 spaces from IN_JAIL, **or**
    4.5.2.2. Wait out **2 turns** in jail. On the third turn after
             being jailed they are released automatically and roll
             normally.
4.5.3. Properties owned during jail still collect rent from the
       opponent.

### 4.6 GO tile / IN_JAIL tile (jail visit, not jailed) / blank tiles

4.6.1. No effect on arrival (other than the GO start bonus which
       triggers on **passing** GO, not on landing).

## 5. Selling and out-of-money

5.1. At any point during the current player's turn, they may
     **sell** anything they own to raise liquid:
    5.1.1. Sell a hotel → refund $100, leaves a house (2 circles).
    5.1.2. Sell a house → refund $100, leaves land (1 circle).
    5.1.3. Sell the land → refund $50 (mortgage). Marks the tile as
           unowned for rent purposes.
5.2. Selling is voluntary while solvent. If a payment would bankrupt
     the player, the auto-liquidation in §4.1.4 runs in this order:
     sell hotels → sell houses → mortgage land → declare bankruptcy.

## 6. Win condition

6.1. Game ends the moment one player is bankrupt. The other player
     is declared winner.
6.2. There is no fixed turn limit and no "first to N dollars" rule.

## 7. UI surfaces relevant to gameplay

7.1. **Game board** in the center, with the live cube positions and
     ownership circles overlay.
7.2. **Game state card** (top-right): turn, last dice, both positions,
     `is_YOLO` toggle, save/load buttons.
7.3. **Dice Status card**: dice face + Roll/Apply/End-turn/Reset
     buttons split around the dice image.
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

## Appendix — gaps vs. current implementation (TODO)

These items are spec, not yet code:

- **Uniform $100 / $200 / $300 pricing**. Current code uses each
  tile's `price_buy` and `price_building` from the board JSON
  ($60–$400 / $50–$200). Spec wants flat $100 per tier.
- **Upgrade on revisit (§4.1.2)**. Current code only shows the Buy
  modal on the *first* arrival at an unowned tile; revisiting an
  already-owned tile is a no-op. Spec wants the upgrade modal.
- **Jail mechanic (§4.5)**. `effects.go_to_jail` only teleports to
  the IN_JAIL tile and does **not** set `in_jail = True`, so the
  escape-on-6 / wait-2-turns logic is unimplemented.
- **Chance as ±$100 only (§4.4)**. Current `chance.json` carries the
  full Monopoly deck (advance-to-tile, jail-free cards, repairs, etc.).
  Spec wants two cards: `+$100` and `−$100` only.
- **Liquid / Assets split UI (§2.1)**. Current UI only shows liquid
  (`balance`). Spec wants both, with assets computed live.
- **Manual sell endpoints (§5.1) wired to the UI**. The backend has
  `mortgage` / `sell_building` endpoints, but no buttons surface them
  yet.
