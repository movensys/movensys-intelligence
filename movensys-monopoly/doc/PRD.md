# PRD — movensys-monopoly

**Owner:** sjhwang@movensys.com
**Status:** Draft v0.2 (2026-04-23)
**Sibling:** `movensys_vlm` (same repo)
**Easy read:** [`PRD_easy.md`](./PRD_easy.md)

---

## 1. Summary

사용자 1명과 로봇팔 1대가 실물 모노폴리 보드로 플레이하는 단일 FastAPI 서비스.
게임 엔진·보드 UI·돈/프로퍼티 관리·카메라 프록시를 담당한다.
**핵심 불변식:** AI·로봇이 하나도 기동되지 않아도 Board 1/2/3 전부가 완전 동작한다.

### 1.1 Key decisions (v0.2, 2026-04-23)
1. **Robot 플레이어 의사결정**: Gemma 4가 양쪽 플레이어 모두 해석. Gemma 미기동 시 내장 **greedy policy** fallback (살 수 있으면 산다 / 임대료 즉시 지불 / 감옥 탈출 가능한 최저 비용 수단 선택).
2. **Intent schema 소유권**: **본 패키지가 정의**, Gemma 팀은 이 스펙에 맞춤 (§8.2).
3. **Whisper UX**: 브라우저 push-to-talk 버튼 → 녹음 종료 시 `POST /stt` 파일 업로드 (§8.1).
4. **카드 아트**: 자체 제작 SVG. 게임 정보(가격·임대료)는 Hasbro 표준 유지, 색·레이아웃·폰트는 trade-dress 회피 (§9.1).
5. **Board 1**: Monopoly Short Game PNG 분석 기반 **20칸** 확정 (§7.2, `static/assets/boards/board1.json`).
6. **`ros2_node.py` 범위**: 카메라 구독 + **Isaac Sim 카드 소환 이벤트 토픽** publish (§12).
7. **Debug 라우트 가드**: `MONOPOLY_DEBUG_ROUTES` env 플래그로 Production 배포 시 `/api/debug/*` 비활성 (§5.10, §10.1).

---

## 2. Scope

### 2.1 In
- 게임 규칙 엔진 (Board 1/2/3)
- REST + WebSocket API
- 보드/돈/property UI
- ROS 2 카메라 토픽 구독·프록시
- 외부 FastAPI 3종 어댑터 (Whisper / Gemma 4 / Robot)

### 2.2 Out
- 로봇 궤적 계획 (Dice/Horse pick-and-place FastAPI가 담당)
- 음성 인식 모델, LLM 모델, 비전 모델 (외부 팀)
- Isaac Sim 물리 시뮬레이션
- 3인 이상 플레이, 네트워크 멀티플레이
- 사용자 계정/인증 (로컬 데모 전용)

### 2.3 Assumptions
- 플레이어는 정확히 2명 (user, robot)
- 서버 인스턴스당 게임 1개 (싱글턴 `GameState`)
- 로컬 네트워크 전용, 외부 인증 없음
- 인메모리 상태 기본, 저장은 선택 사양

---

## 3. Architecture

### 3.1 Three-layer separation

```
Intent Source  →  Game Engine  →  Physical Executor
(무엇을 할지)      (규칙·상태)     (실세계 동작)

Whisper+Gemma       game/*         Robot FastAPI
  또는                               또는
수동 UI 버튼                        Headless no-op
```

- **Intent Source**와 **Physical Executor**는 교체 가능한 어댑터.
- **Game Engine**은 순수 Python, ROS 2/외부 HTTP 의존 없음, pytest로 전수 검증.
- 게임 엔진은 물리 실행 완료를 기다리지 않는다 (fire-and-forget).

### 3.2 Operating modes

각 축은 독립 — 조합 가능 (예: Whisper만 활성, 나머지는 수동).

| Axis | off 기본값 | on 조건 |
|---|---|---|
| STT | 수동 텍스트 입력창 | `STT_SERVICE_URL` 설정 |
| LLM | UI 버튼이 직접 엔드포인트 호출 | `LLM_SERVICE_URL` 설정 |
| Robot | no-op (화면 애니만 재생) | `ROBOT_SERVICE_URL` 설정 |
| Camera | "No stream" 플레이스홀더 | ROS 2 토픽 publish 중 |

### 3.3 Request flow (정상 턴)

```
[Utterance or UI click]
        ↓
POST /api/dice/request       (서버가 dice_source 분기)
        ↓
POST /api/dice/submit        (값 등록, FSM MOVING)
        ↓
Fire-and-forget Robot /horse/move  (응답 대기 X)
POST /api/move/apply         (서버가 tile 갱신, FSM RESOLVE_TILE)
        ↓
rules.resolve_tile()         (타일 종류별 분기 — 결정론적)
        ↓
/api/stream/game WS event    (UI 업데이트)
```

---

## 4. Data Model

단일 진실 원천 (single source of truth)은 `game/state.py`의 `GameState`. 모든 WS 이벤트와 REST 응답은 이를 투영한다.

### 4.1 Core types

```python
Player     = Literal["user", "robot"]
TileKind   = Literal["start", "property", "railroad", "utility",
                     "tax", "chance", "community_chest",
                     "jail_visit", "go_to_jail", "free_parking", "blank"]
BoardId    = Literal["1", "2", "3"]
DiceSource = Literal["manual", "rng", "robot"]
FSM        = Literal["IDLE", "TURN_START", "MOVING", "RESOLVE_TILE",
                     "AWAIT_DECISION", "PAY_RENT", "END_TURN", "GAME_OVER"]
```

### 4.2 GameState

```python
class GameState:
    board_id: BoardId
    fsm: FSM
    turn: Player
    turn_number: int
    positions: dict[Player, int]            # tile_index
    players: dict[Player, PlayerState]
    properties: dict[str, PropertyCard]     # id = f"{board_id}:{slug}"
    last_dice: tuple[int, int] | None       # (d1, d2); Board 1/2만 더블 사용
    doubles_streak: int                     # Board 2 jail 규칙
    decks: { "chance": list[Card], "community_chest": list[Card] }
    winner: Player | None
    config: RuntimeConfig
```

### 4.3 PlayerState / Money

```python
class PlayerState:
    id: Player
    balance: int
    in_jail: bool
    jail_turns_left: int                    # 0..3 (Board 2)
    has_jail_free_card: bool
    color: str                              # hex, default user=#E53935 robot=#1E88E5

class Transaction:
    amount: int                             # 부호 포함
    reason: Literal["buy", "build", "rent", "tax", "chance", "community",
                    "jail_exit", "mortgage", "unmortgage", "start_bonus",
                    "building_sale", "bankruptcy_transfer"]
    counterparty: Player | "bank" | None
    timestamp: datetime
```

### 4.4 PropertyCard (kind별 구조)

```python
class PropertyCard:
    id: str
    tile_index: int
    name: str
    kind: Literal["property", "railroad", "utility"]
    color_group: str | None                 # property만
    price_buy: int
    price_building: int | None              # property만
    rent_table: list[int] | None            # property: [base, h1..h4, hotel]
    owner: Player | None
    houses: int                             # 0..4, property만
    has_hotel: bool
    mortgaged: bool
```

임대료는 `rules.compute_rent(card, state)`가 kind별로 분기 계산 — `rent_table`을 직접 쓰지 않는다 (§7.3 독점 보너스·역 임대료·유틸리티 임대료 참조).

### 4.5 Card (Chance / Community Chest 공용)

효과는 **구조화된 JSON**. LLM 해석 없이 `rules.py`가 결정론적으로 적용한다.

```python
class Card:
    id: str
    deck: Literal["chance", "community_chest"]
    text: str                               # 표시용
    effect: CardEffect

CardEffect = Union[
    MoveToTile,           # {type, tile_index, collect_on_pass}
    MoveRelative,         # {type, delta}
    Collect,              # {type, amount}
    Pay,                  # {type, amount, to: Literal["bank","opponent"]}
    GoToJail,             # {type}
    GrantJailFreeCard,    # {type}
    CollectPerBuilding,   # {type, per_house, per_hotel}
]
```

### 4.6 WS event envelope

모든 `/api/stream/*` 메시지는 동일 envelope.

```json
{
  "event_id": "uuidv4",
  "ts": "2026-04-23T12:34:56.789Z",
  "type": "property_card_shown",
  "payload": { "property_id": "board2:mediterranean" }
}
```

### 4.7 REST error envelope

비-2xx 응답은 모두 아래 형식. 요청 correlation 은 `event_id`.

```json
{
  "error": {
    "code": "INSUFFICIENT_FUNDS",
    "message": "balance 100 < required 200",
    "details": { "balance": 100, "required": 200 },
    "event_id": "uuidv4"
  }
}
```

Error codes (고정 집합):
`INVALID_STATE` · `TILE_MISMATCH` · `PROPERTY_OWNED` · `NOT_OWNER`
`INSUFFICIENT_FUNDS` · `MONOPOLY_REQUIRED` · `JAIL_EXIT_UNAVAILABLE`
`ADAPTER_UNAVAILABLE` · `BAD_REQUEST` · `NOT_FOUND`

---

## 5. API Surface

모든 경로는 `/api` 아래. JSON in/out. WebSocket은 `/api/stream/*`.

### 5.1 Game control

| Method | Path | Body → Response | Notes |
|---|---|---|---|
| POST | `/game/start` | `{board: BoardId}` → `{fsm, turn}` | IDLE에서만 허용 |
| POST | `/game/end_turn` | `{}` → `{fsm, turn}` | RESOLVE 완료 후 |
| GET  | `/game/state` | → `GameState` | 전체 스냅샷 |
| GET  | `/game/winner` | → `{winner: Player \| null}` | Board 3 필수 |
| GET  | `/game/next_prompt` | → `{hint: string}` | LLM용 텍스트 힌트 |
| POST | `/game/config` | `RuntimeConfig` 일부 | 색상·dice_source·auctions_enabled |
| WS   | `/stream/game` | FSM·턴·승패 이벤트 | envelope §4.6 |
| GET  | `/health` | → `{status: "ok"}` | |

### 5.2 Dice & movement

| Method | Path | Body → Response | Notes |
|---|---|---|---|
| POST | `/dice/request` | `{}` → `{source}` | `dice_source`에 따라 분기 |
| POST | `/dice/submit` | `{value: 1..6 \| [1..6, 1..6], source: DiceSource}` → `{fsm}` | 더블 검출 포함 |
| POST | `/move/apply` | `{player, from_tile, to_tile}` → `{fsm, resolved: ResolveResult}` | mismatch → 409 TILE_MISMATCH |
| WS   | `/stream/board` | 말 위치 변경 이벤트 | |

### 5.3 Money

| Method | Path | Body → Response | Notes |
|---|---|---|---|
| GET  | `/money` | → `{user, robot}` | 잔액 스냅샷 |
| GET  | `/money/{player}` | → `{balance, history}` | |
| POST | `/money/transfer` | `{payer, payee, amount, reason}` → `{balances}` | **internal only** — `rules.py`만 호출 |
| WS   | `/stream/money` | delta 이벤트 | |

### 5.4 Property

| Method | Path | Body → Response | Notes |
|---|---|---|---|
| GET  | `/properties` | → `list[PropertyCard]` | |
| GET  | `/properties/{id}` | → `PropertyCard` | |
| POST | `/properties/{id}/decide` | `{action: "skip"\|"buy"\|"build", house_count?}` | 카드 도착 시 결정 |
| POST | `/properties/{id}/build` | `{houses?: int, hotel?: bool}` | 독점 필요 |
| POST | `/properties/{id}/mortgage` | `{}` | 구매가 50% 수령 |
| POST | `/properties/{id}/unmortgage` | `{}` | 저당가 × 1.1 지불 |
| POST | `/properties/{id}/sell_building` | `{}` | 건물 1채, 절반가 회수 |
| WS   | `/stream/properties` | 소유·건물 변경 | |

### 5.5 Effects (Chance / Community Chest 공용)

| Method | Path |
|---|---|
| POST | `/effects/move_to_tile` |
| POST | `/effects/move_relative` |
| POST | `/effects/collect` |
| POST | `/effects/pay` |
| POST | `/effects/go_to_jail` |
| POST | `/effects/grant_jail_free_card` |

### 5.6 Jail (Board 2 전용)

| POST | `/jail/attempt_exit` | `{method: "dice"\|"pay"\|"card"}` → `{exited, reason}` |

### 5.7 Robot proxy (Dice/Horse FastAPI 어댑터)

| Method | Path | 외부 호출 | Stub |
|---|---|---|---|
| POST | `/robot/base_position` | `POST {ROBOT}/base_position` | no-op 200 |
| POST | `/robot/roll_dice` | `POST {ROBOT}/dice/roll` | RNG 생성 |
| POST | `/robot/move_piece` | `POST {ROBOT}/horse/move` | no-op 200 |
| GET  | `/robot/health` | → `{mode: "live"\|"stub", url?}` | `ROBOT_SERVICE_URL` 기반 |

### 5.8 Cameras (ROS 2 프록시 — `movensys_vlm`에서 이식)

| WS | `/stream/image_top/{rgb,depth,camera_info}` |
| WS | `/stream/image_hand/{rgb,depth,camera_info}` |

### 5.9 Board assets

| GET | `/board/definition?id={1,2,3}` — 타일 레이아웃 JSON |
| GET | `/board/snapshot` → `{image_b64, prompt_hint}` — LLM 판독용 (없어도 게임 진행) |

### 5.10 Debug / Manual

개발·검증·CI에서 사용. **`MONOPOLY_DEBUG_ROUTES=false`** 설정 시 아래 전체 라우트가 404로 응답 (Production 가드).

| POST | `/debug/inject_utterance` | Whisper 우회 — `{text}` |
| POST | `/debug/simulate_llm_intent` | Gemma 우회 — `{intent, args}` §8.2 |
| POST | `/debug/force_dice` | 주사위 고정 — `{value}` or `{d1, d2}` |
| POST | `/debug/force_state` | 시나리오 재현용 `GameState` 덮어쓰기 |

---

## 6. State Machine

```
     IDLE
       │ /game/start
       ▼
   TURN_START ──────────────────────────────┐
       │ /dice/submit                       │
       ▼                                    │
    MOVING                                  │
       │ /move/apply                        │
       ▼                                    │
   RESOLVE_TILE ──┬──────────┬──────────┐   │
                 │ empty    │ owned    │ special
                 ▼          ▼          ▼
          AWAIT_DECISION  PAY_RENT   (jail/tax/
                 │          │         chance/...)
                 │ decide   │ paid OR bankrupt
                 ▼          ▼
                END_TURN ◄──┤
                 │          └─► GAME_OVER
                 └─> TURN_START (next player) ─┘
```

전이별로 `/stream/game` 이벤트 발행: `{event_id, ts, type: "fsm_transition", payload: {from, to, trigger}}`.

---

## 7. Game Rules

### 7.1 Board 3 — 12-tile headless smoke

- 12개 빈 타일 + START, **3×5 직사각형 퍼리미터**
- 물리 원본: `movensys-simulation/dobot_cr3a/monopoly_board.drawio.png` → `static/assets/boards/board3_physical.png`
- UI 대체 SVG: `static/assets/boards/board3_blank.svg` (타일 번호 오버레이)
- 돈·property·chance 없음, `fsm`은 `IDLE → TURN_START → MOVING → END_TURN` 루프만
- 승리: 한 바퀴 먼저 완료 (`positions[p]`가 wrap 발생)
- **목적:** E2E 파이프라인(dice→move→winner) 검증 전용

### 7.2 Board 1 — short board (20 tiles, image-analyzed)

- 타일 **20칸 확정** — 출처 `static/assets/boards/board1.json`, `Monopoly_short.png` 분석 기반
- 시드 잔액 $1,000, 시작점 통과 +$100
- 포함 타일: GO · Jail Visit · Free Parking · Go To Jail (4 corners) · property 7 · railroad 3 · utility 2 · chance 2 · community chest 1 · income tax 1
- 감옥 FSM·독점 보너스 **없음** (단순화) — 로직은 재사용하되 `monopoly_bonus_multiplier: 1`
- 색상 그룹당 1개 타일뿐이라 독점 불가 — 설계 의도

### 7.3 Board 2 — full rules (all pure-logic, no AI/robot needed)

시드 잔액 $1,500. 모든 항목 `rules.py` 단위 테스트로 검증.

**7.3.1 Jail**
- 투옥: "Go to Jail" 타일(30) 도착 / 더블 3연속 / Chance·CC "Go to Jail"
- 탈출 수단: (a) 더블 굴리기 (b) $50 지불 (c) `has_jail_free_card` 소비 (d) 3턴째 자동 $50
- 엔드포인트: `POST /jail/attempt_exit`

**7.3.2 Railroad (역) × 4** — tile 5/15/25/35
- `kind="railroad"`, 구매가 $200, 저당가 $100
- 임대료 = $25 × 2^(owner 보유 개수 − 1) ∈ {25, 50, 100, 200}

**7.3.3 Utility × 2** — tile 12/28
- `kind="utility"`, 구매가 $150
- 임대료 = `last_dice_sum × (4 if owned==1 else 10)`

**7.3.4 Tax tiles**
- Income Tax (tile 4): $200 고정 (원본 "10% or $200 선택"은 config 토글)
- Luxury Tax (tile 38): $100 고정

**7.3.5 Monopoly bonus (색상 그룹 독점)**
- `is_monopoly(group, owner)` → 빈 property 임대료 2배
- 건물 건설 조건: 해당 그룹 독점 + **균등 건설 규칙** (같은 그룹 내 건물 수 차이 ≤ 1)

**7.3.6 Community Chest** — tile 2/17/33
- `game/community_chest.py`에 16장 기본 덱
- 구조는 Chance와 동일 (공용 `CardEffect`, 공용 `/effects/*`)
- "Get Out of Jail Free" 포함 (사용 시 덱 하단 반환)

**7.3.7 Mortgage**
- 저당가 = 구매가 × 0.5, 임대료 수취 불가
- 해제 = 저당가 × 1.1

**7.3.8 Start bonus**
- 통과·도착 공통 +$200

**7.3.9 Auction (옵션, 기본 OFF)**
- `config.auctions_enabled`로 토글. 활성 시 `/auction/start`, `/auction/bid` 추가.

**7.3.10 Bankruptcy**
- 임대료·세금 지불 불가 → 자동 매각 순서: (1) 건물 절반가 (2) property 저당 (3) 남은 자산 → 여전히 부족 시 `fsm → GAME_OVER`
- 모든 자산을 상대 플레이어로 이전 (bank가 수령자면 해제)

**7.3.11 Robot player policy (Gemma 미기동 시 fallback)**
Gemma 4 어댑터가 off면 "robot" 플레이어의 결정은 내장 greedy policy가 대체한다. `game/policies/greedy.py`.

결정 규칙 (deterministic, 설정으로 override 가능):
- **빈 property 도착**: `balance ≥ price_buy + price_building` 이면 매입 + 집 1채. 부족하면 매입만. 그마저도 부족하면 skip.
- **건물 증축 기회**: 독점 + 균등 건설 규칙 충족 + `balance ≥ price_building × 2` 이면 추가 1채. 그 외 skip.
- **감옥 탈출**: `has_jail_free_card` → 카드 사용; 그 외 `balance ≥ $50` → 지불; 나머지 → 더블 시도.
- **임대료**: 지불 가능하면 지불. 불가면 §7.3.10 자동 처리.
- **경매 (선택 활성 시)**: `price_buy × 0.75` 까지 입찰, 초과하면 pass.

Greedy policy가 발동했는지 여부는 WS 이벤트 payload에 `decision_source: "greedy" | "gemma" | "manual"`로 표기.

### 7.4 Tile resolution routing

```python
def resolve_tile(state, player, tile) -> ResolveResult:
    match state.board.tile_kind(tile):
        case "start":           return collect_start_bonus(...)
        case "property" | "railroad" | "utility":
                                return resolve_property(...)     # §7.3.2-7.3.5
        case "chance" | "community_chest":
                                return draw_card(...)            # §7.3.6
        case "tax":             return apply_tax(...)            # §7.3.4
        case "go_to_jail":      return send_to_jail(...)         # §7.3.1
        case "jail_visit":      return ResolveResult.noop()
        case "free_parking":    return ResolveResult.noop()
        case "blank":           return ResolveResult.noop()      # Board 3
```

---

## 8. Adapters

세 어댑터 모두 `adapters/` 아래. 동일한 패턴: **URL 없으면 stub**, **있으면 httpx 호출**. 타임아웃·재시도는 로봇만 엄격(§11.1).

### 8.1 Whisper STT
- **UX**: 브라우저 push-to-talk 버튼. 길게 누르고 있는 동안 `MediaRecorder`로 녹음, 떼면 `multipart/form-data`로 업로드.
- **외부**: `POST {STT_SERVICE_URL}/stt` `audio: <file>` (wav/opus) → `{text: string, language?: "ko"|"en"}`
- **본 패키지 접점**: 브라우저 → `POST /api/stt` 어댑터 → 외부 Whisper. 결과는 `/api/utterance/submit {text}`로 연결 (내부).
- **Stub**: `STT_SERVICE_URL` 빈 상태면 버튼은 비활성, 대신 텍스트 입력창. `/api/debug/inject_utterance {text}`로도 주입 가능.

### 8.2 Gemma 4 LLM (intent schema는 **본 패키지 소유**)

**Request**: `POST {LLM_SERVICE_URL}/infer`
```json
{
  "text": "I'll buy it and build a house",
  "image_b64": null,
  "context": {
    "fsm": "AWAIT_DECISION",
    "turn": "user",
    "board_id": "2",
    "pending_decision": {
      "type": "property_arrival",
      "property_id": "board2:mediterranean",
      "player_balance": 1400
    }
  }
}
```

**Response** (intent 어휘는 고정):
```json
{ "intent": "buy_and_build", "args": { "house_count": 1 }, "confidence": 0.93 }
```

**고정된 intent 어휘:**

| intent | args | 대응 엔드포인트 |
|---|---|---|
| `start_game` | `{board}` | `/game/start` |
| `roll_dice` | `{}` | `/dice/request` |
| `end_turn` | `{}` | `/game/end_turn` |
| `buy` | `{property_id}` | `/properties/{id}/decide` with action=buy |
| `buy_and_build` | `{property_id?, house_count}` | `/properties/{id}/decide` with action=build |
| `skip` | `{}` | `/properties/{id}/decide` with action=skip |
| `jail_exit` | `{method: "dice"\|"pay"\|"card"}` | `/jail/attempt_exit` |
| `mortgage` | `{property_id}` | `/properties/{id}/mortgage` |
| `unmortgage` | `{property_id}` | `/properties/{id}/unmortgage` |
| `sell_building` | `{property_id}` | `/properties/{id}/sell_building` |
| `board_query` | `{}` | `/game/state` + `/board/snapshot` (정보 요청) |
| `unknown` | `{reason}` | UI가 재질문 프롬프트 표시 |

- **VLM 용도**: `image_b64`가 실릴 때는 보드 snapshot 판독 — Gemma는 말 위치를 확인하고 `board_query`로 응답. 실제 타일 결정은 서버가 이미 알고 있음 (§3.3, §5.9).
- **Stub**: UI 수동 버튼이 위 엔드포인트를 직접 호출. `/api/debug/simulate_llm_intent`로 임의 intent 주입 가능.
- **Gemma 미기동 + robot 턴**: §7.3.11 greedy policy가 대체.

### 8.3 Robot (Dice/Horse) — fire-and-forget
- 외부:
  - `POST {ROBOT_SERVICE_URL}/dice/roll` → `{value: 1..6}` (동기, 타임아웃 10s)
  - `POST {ROBOT_SERVICE_URL}/horse/move` `{player, from_tile, to_tile}` → `{accepted: bool}` (**즉시 반환**, 실제 완료는 WS `/robot/status`로 별도 통지)
  - `POST {ROBOT_SERVICE_URL}/base_position` → `{accepted}`
- **게임 엔진은 `/horse/move` 완료를 기다리지 않는다.** `/move/apply`가 먼저 상태를 갱신하고 UI 애니메이션 재생. 로봇 실패 시 WS `event: "robot_error"` 로 UI에만 알림 (게임 진행 계속).
- Stub: 주사위는 `dice_source="rng"` 또는 `"manual"`, 말 이동은 no-op.
- `/api/robot/health` → `{mode: "live"|"stub", url?}` 는 CI 불변식 (§14).

---

## 9. UI

SPA. 서버측 세션 없음 — `/game/state` 폴링/WS로만 동기화.

- **Top bar**: 두 플레이어 잔액 (지폐 스택 + 숫자), 턴 표시, 모드 배지 (`AI:off/on`, `Robot:off/on`)
- **Board canvas**: 보드 이미지 + 말 아이콘 슬라이드 애니메이션 (400ms)
- **Money widget**: 이동 시 지폐 페이드/플라이 애니메이션 (600ms), 사이드 토글로 최근 10건 history
- **Property sidebar (좌/우)**: 색상그룹별 썸네일, 건물 수 아이콘 오버레이, 클릭 시 카드 모달
- **Manual control panel**: 모든 FSM 전이를 버튼으로 트리거 — 개발·시연 상시 활성
- **Camera thumbnails**: 우측 하단, WS 스트림 미공급 시 "No stream"
- **Card modal**: 빈 property 도착 시 자동 표시, `skip / buy / buy+build N` 버튼

### 9.1 Card art assets (**self-produced, v1 확정**)

Hasbro trade dress 회피 + 게임 정보 유지.

- **Property/Railroad/Utility 카드**: 템플릿 SVG + JSON 렌더. 수동 작업 없음.
  - 템플릿: `static/assets/property_cards/{template,_railroad_template,_utility_template}.svg`
  - 렌더러: `scripts/render_cards.py {board_json} --out {dir}`
  - 산출물: `static/assets/property_cards/board{1,2}/*.svg` (Board 2는 28장, Board 1은 12장)
  - 색상 그룹 hex는 board JSON의 `color_group_hex`에서 받는다 (단일 진실 원천)
- **Board 3 SVG**: `static/assets/boards/board3_blank.svg` — 4×4 perimeter, 12 타일
- **Chance / Community Chest**: 카드 JSON 덱 (`game/chance.json`, `game/community_chest.json`) — 각 16장. 이미지 없이 텍스트만으로 규칙 동작. UI는 텍스트 모달로 표시.
- **Board 1/2 메인 보드 이미지**: 현재는 원본 PNG/JPG를 그대로 사용 (내부 데모 한정). 외부 배포 시 재제작.

---

## 10. Configuration

### 10.1 Env vars

| Var | Default | Effect |
|---|---|---|
| `STT_SERVICE_URL` | (empty) | 비면 STT stub — 텍스트 입력창 활성 |
| `LLM_SERVICE_URL` | (empty) | 비면 LLM stub — 수동 버튼 / greedy policy |
| `ROBOT_SERVICE_URL` | (empty) | 비면 Robot stub — RNG 주사위 + no-op 이동 |
| `ROS_DISTRO` | `jazzy` | ROS 2 배포판 |
| `ROS_DOMAIN_ID` | `0` | DDS 도메인 |
| `RMW_IMPLEMENTATION` | `rmw_fastrtps_cpp` | |
| `MONOPOLY_PORT` | `8000` | FastAPI 포트 |
| `MONOPOLY_LOG_LEVEL` | `INFO` | |
| `MONOPOLY_PERSISTENCE_PATH` | (empty) | 비면 인메모리만 |
| `MONOPOLY_DEBUG_ROUTES` | `true` | `false`면 `/api/debug/*` 404 (Production 가드) |
| `MONOPOLY_ISAAC_TOPIC_CARD_SPAWN` | `/isaac/card_spawn` | ROS 2 publish 토픽명 (§12) |

### 10.2 RuntimeConfig (runtime-editable via `/game/config`)

```python
class RuntimeConfig:
    dice_source: DiceSource = "rng"         # rng | manual | robot
    auctions_enabled: bool = False
    income_tax_mode: Literal["fixed_200", "choose"] = "fixed_200"
    player_colors: dict[Player, str] = {"user": "#E53935", "robot": "#1E88E5"}
```

---

## 11. Non-Functional Requirements

### 11.1 Latency budget
- `/api/health`: p99 < 50ms
- `/api/*` 게임 상태 변경: p99 < 200ms (WS broadcast 포함)
- 로봇 어댑터 HTTP 호출: 타임아웃 5s, 실패 시 `ADAPTER_UNAVAILABLE` 로그 + 게임 진행은 계속

### 11.2 Concurrency
- 게임 1개 / 서버 인스턴스
- FSM 전이는 `asyncio.Lock`으로 직렬화
- WS 이벤트는 broadcast, 순서 보장 (`event_id` 단조 증가)

### 11.3 Persistence
- 기본 인메모리. `MONOPOLY_PERSISTENCE_PATH` 설정 시 `GameState`를 JSON으로 주기 저장 (5초)
- 기동 시 파일 존재하면 복원, `fsm != IDLE`이면 진행 중 게임 재개

### 11.4 Observability
- 구조화 JSON 로그: `{ts, level, event_id, fsm, type, ...}`
- 모든 REST·WS 이벤트에 `event_id` (uuid4), 로그로 상관
- Prometheus `/metrics` (선택): `fsm_transitions_total`, `rule_violations_total`, `adapter_calls_total{adapter,outcome}`

### 11.5 ROS 2 node scope (`ros2_node.py`)

단일 `rclpy` 노드가 다음을 담당:

| 방향 | 토픽 | 메시지 | 용도 |
|---|---|---|---|
| Sub | `/image_top/rgb`, `/image_top/depth`, `/image_top/camera_info` | `sensor_msgs/*` | FastAPI WS 프록시 |
| Sub | `/image_hand/rgb`, `/image_hand/depth`, `/image_hand/camera_info` | 동일 | 동일 |
| Pub | `${MONOPOLY_ISAAC_TOPIC_CARD_SPAWN}` (기본 `/isaac/card_spawn`) | `std_msgs/String` (JSON payload) | Chance/CC 카드 뽑을 때 Isaac Sim에 물리 카드 소환 요청 |

Payload 예시 (카드 소환):
```json
{ "event_id": "uuid", "deck": "chance", "card_id": "advance_to_go", "tile_index": 7 }
```

Isaac Sim이 기동되지 않아도 토픽은 그냥 publish만 — 구독자 없으면 drop. 본 패키지는 배달 보장 책임 없음.

---

## 12. Repo Layout

```
movensys-monopoly/
├── doc/
│   ├── PRD.md
│   ├── PRD_easy.md
│   └── running.md              ← 실행법 (TBD)
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── entrypoint.sh
├── main.py                     ← FastAPI entry
├── router.py                   ← REST + WS routes
├── ros2_node.py                ← ROS 2 node: camera subscribers + Isaac card-spawn publisher
├── game/
│   ├── state.py                ← GameState singleton
│   ├── boards.py               ← loader for static/assets/boards/board{1,2,3}.json
│   ├── properties.py           ← rent computation (property/railroad/utility)
│   ├── chance.py               ← deck loader (reads chance.json)
│   ├── chance.json             ← 16-card deck (structured effects)
│   ├── community_chest.py      ← Board 2
│   ├── community_chest.json    ← 16-card deck
│   ├── jail.py                 ← Board 2
│   ├── rules.py                ← resolve_tile, transfers, bankruptcy
│   └── persistence.py          ← JSON save/load (optional)
├── adapters/
│   ├── stt.py                  ← Whisper client
│   ├── llm.py                  ← Gemma client (intent dispatcher)
│   └── robot.py                ← Dice/Horse client
├── policies/
│   └── greedy.py               ← Robot fallback policy (§7.3.11)
├── static/
│   ├── index.html
│   ├── cameras.html
│   └── assets/{boards,property_cards,chance_cards}/
├── tests/
│   ├── game/                   ← unit tests (pure Python)
│   ├── board1/
│   ├── board2/
│   └── e2e/                    ← headless FastAPI E2E
├── scripts/
│   ├── ci_local.sh
│   └── render_cards.py         ← SVG 카드 일괄 렌더링
└── requirements.txt
```

---

## 13. Testing

모든 자동 테스트는 외부 FastAPI 3종 기동 없이 통과해야 한다 — `STT_SERVICE_URL`/`LLM_SERVICE_URL`/`ROBOT_SERVICE_URL` 빈 값에서 CI 돌음.

| Suite | Scope | 도구 |
|---|---|---|
| `tests/game/` | 규칙 엔진 순수 로직 — 임대료 계산, 독점 검사, 파산 순서 | pytest |
| `tests/board1/` | Board 1 시나리오 (매입·건설·임대·chance) | pytest + 픽스처 상태 |
| `tests/board2/` | Jail FSM, 역·유틸리티, 세금, 독점 배수, 균등 건설, CC 덱, 저당 | pytest |
| `tests/e2e/` | FastAPI 앱 실제 기동 (httpx AsyncClient), Board 3 한 바퀴 → winner | pytest-asyncio |
| Adapter stub | 3개 env 미설정 상태에서 §5.7 `/robot/health` → `{mode: "stub"}` | pytest |
| UI 회귀 | Playwright (선택) — 돈 애니메이션·말 이동·모달 | 별도 워크플로 |

**핵심 테스트 케이스 (Board 2):** jail 3-턴 자동 탈출, 역 4개 보유 임대료 $200, 유틸 2개 독점 임대료 계수 10, 균등 건설 위반 시 409, 독점 그룹 임대료 2배, bankruptcy 자산 이전, CC "Get Out of Jail Free" 덱 하단 반환.

---

## 14. CI/CD

`.github/workflows/movensys-monopoly.yml` — `movensys_vlm.yml` 스타일 준수.

**트리거:** `movensys-monopoly/**` 경로의 `main`/`devel` PR

**스텝 (순서):**
1. Checkout + ROS 2 설치 (ros-tooling/setup-ros)
2. `pip install -r requirements.txt` (+ pytest, httpx, uvicorn)
3. `py_compile` 전체 `.py`
4. `uvicorn main:app` 기동 → `curl /api/health` 200
5. Stub 불변식: `/api/robot/health` → `{mode: "stub"}` (env 미설정 상태)
6. `pytest tests/` — **존재하는 suite 전부 실행**, 새 테스트는 자동 픽업

**CI에 넣지 않음:** Docker Compose 빌드, 외부 FastAPI 실제 호출, Isaac Sim, UI 회귀 (별도 워크플로).

**회귀 방지 정책:** 테스트 디렉토리 삭제는 코드 리뷰에서 차단 (CI에 milestone 게이팅 로직 넣지 않음 — PR 리뷰 책임).

**로컬 재현:** `scripts/ci_local.sh` — 워크플로 스텝과 1:1 동일.

---

## 15. Milestones

각 마일스톤의 완료 정의는 **CI에서 관찰 가능한 Acceptance Criteria**. Definition of Done = AC 전수 통과 + `main` 병합.

| # | Scope | Acceptance Criteria |
|---|---|---|
| M0 | Skeleton + Docker + CI | `docker compose up` → `/api/health` 200 · `/api/robot/health` → stub · CI green |
| M1 | Board 3 headless E2E | `tests/e2e/test_board3.py` 한 바퀴 → `GET /game/winner` 가 non-null |
| M2 | Board 1 full rules | `tests/board1/` 전수 통과 · 매입·건설·임대·파산 시나리오 |
| **M3** | **Board 2 full rules** | `tests/board2/` §7.3.1-7.3.10 전수 통과 — 외부 FastAPI 기동 없이 |
| M4 | Camera stream proxy | WS `/stream/image_top/rgb` 프레임 수신 (ROS 2 publish 중일 때) |
| M5 | Robot adapter integration | `ROBOT_SERVICE_URL` 설정 시 실제 dice/horse 호출 (수동 테스트) |
| M6 | Whisper adapter integration | `STT_SERVICE_URL` 설정 시 발화 → 텍스트 → 엔드포인트 경로 |
| M7 | Gemma adapter integration | `LLM_SERVICE_URL` 설정 시 발화/이미지 → intent → 엔드포인트 |
| M8 | (옵션) Chance art + Isaac | 카드 이미지 교체 + Isaac 카드 소환 토픽 |

**불변식:** 모든 마일스톤에서 `STT/LLM/ROBOT_SERVICE_URL`을 모두 비운 상태로 CI가 녹색이어야 한다.

---

## 16. Development Checklist

§15 Milestones를 PR 단위로 쪼갠 실행 목록. 각 항목은 **독립 PR 1건 크기** 를 지향하고, 대응되는 PRD 섹션을 괄호로 링크.
Definition of Done은 체크 + CI green + 해당 마일스톤의 §15 AC 충족.

### 16.1 M0 — Skeleton + Docker + CI
- [x] `requirements.txt` (fastapi, uvicorn, httpx, pydantic, python-multipart)
- [x] `docker/Dockerfile`, `docker/docker-compose.yml`, `docker/entrypoint.sh` (§12, §10.1)
- [x] `main.py` FastAPI entry — lifespan, 이벤트 ID 미들웨어, static 서빙
- [x] `router.py` skeleton — `GET /api/health` → `{"status":"ok"}` (§5.1)
- [x] `adapters/{stt,llm,robot}.py` — 빈 URL에서 stub 모드 기동, 로그 배너
- [x] `GET /api/robot/health` — `{mode: "live"|"stub", url?}` (§5.7)
- [x] `static/index.html` — 최소 플레이스홀더 + 어댑터 모드 배지 (§9)
- [x] `ros2_node.py` skeleton — 노드 기동만, 구독 없음 (§11.5)
- [x] Structured JSON logger with `event_id` (§11.4)
- [x] `MONOPOLY_DEBUG_ROUTES` 게이트 미들웨어 (§5.10, §10.1)
- [ ] CI green: syntax + health + stub 불변식 (§14) — 로컬 `ci_local.sh` 통과 확인됨, GitHub Actions 결과 대기

### 16.2 M1 — Board 3 headless E2E
- [x] `game/state.py` — `GameState`, `PlayerState`, `FSM` enum (§4)
- [x] `game/boards.py` — `static/assets/boards/*.json` 로더
- [x] `game/rules.py` — `apply_move`, wrap 감지, Board 3 승리 판정 (§7.1, §6-A)
- [x] `POST /api/game/start` / `end_turn` / `config` (§5.1)
- [x] `POST /api/dice/request` / `submit` (manual + rng 소스) (§5.2)
- [x] `POST /api/move/apply` + `TILE_MISMATCH` 409 (§4.7, §5.2)
- [x] `GET /api/game/state` / `winner`
- [x] `WebSocket /api/stream/game` + WS envelope (§4.6)
- [x] FSM 전이 이벤트 발행 (§6)
- [x] `asyncio.Lock` 기반 FSM 직렬화 (§11.2)
- [x] `tests/e2e/test_board3_smoke.py` — 한 바퀴 → winner non-null
- [x] `static/index.html` — Board 3 SVG 오버레이 + 말 아이콘 슬라이드

### 16.3 M2 — Board 1 full rules
- [ ] `game/properties.py` — `PropertyCard`, `compute_rent(property)` (§4.4, §7.3.5)
- [ ] `game/chance.py` / `community_chest.py` — 덱 로더 + shuffle + draw
- [ ] `game/rules.py` `resolve_tile()` 라우팅 분기 (§7.4)
- [ ] Buy / Build / Mortgage / Unmortgage / Sell-building 트랜잭션
- [ ] Bankruptcy 시퀀스 (건물 매각 → 저당 → GAME_OVER) (§7.3.10)
- [ ] `POST /api/properties/{id}/{decide,buy,build,mortgage,unmortgage,sell_building}` (§5.4)
- [ ] `POST /api/effects/{move_to_tile,move_relative,collect,pay}` (§5.5)
- [ ] `POST /api/money/transfer` (internal) + `/api/stream/money` (§5.3)
- [ ] `/api/stream/board`, `/api/stream/properties`
- [ ] UI: 상단 머니 위젯 (지폐 애니 600ms) (§9)
- [ ] UI: 좌/우 property 사이드바 (색상 그룹 썸네일)
- [ ] UI: property 도착 모달 (skip / buy / buy+build 버튼)
- [ ] UI: 수동 컨트롤 패널 (모든 FSM 전이 버튼) (§9)
- [ ] `tests/board1/` — buy, rent, build, chance, bankruptcy 시나리오

### 16.4 M3 — Board 2 full rules
- [ ] `compute_rent` railroad 분기 — $25 × 2^(n-1) (§7.3.2)
- [ ] `compute_rent` utility 분기 — dice × 4/10 (§7.3.3)
- [ ] `game/jail.py` FSM — in_jail, jail_turns_left, jail_free_card (§7.3.1)
- [ ] `POST /api/jail/attempt_exit` (§5.6)
- [ ] Double 검출 + triple-double → jail
- [ ] Tax 타일 처리 (소득세 / 사치세) (§7.3.4)
- [ ] Monopoly 보너스 × 2 (§7.3.5)
- [ ] Even-build rule (±1 균등 건설 검증) (§7.3.5)
- [ ] `POST /api/effects/{go_to_jail,grant_jail_free_card,pay_per_building,collect_from_each_player,move_to_nearest}` (§5.5)
- [ ] `policies/greedy.py` — robot fallback policy (§7.3.11)
- [ ] `decision_source` 태깅 WS payload (§7.3.11)
- [ ] Config toggle `auctions_enabled` (기본 off) (§10.2)
- [ ] `tests/board2/` — jail FSM, 역/유틸리티 임대료, 세금, 독점 배수, 균등 건설, CC "Get Out of Jail", 저당 사이클, greedy policy 결정

### 16.5 M4 — Camera stream + Isaac topic
- [ ] `ros2_node.py` 6개 카메라 토픽 구독 (rgb/depth/camera_info × top/hand) (§11.5)
- [ ] WS 프록시 `/api/stream/image_top/*`, `/api/stream/image_hand/*`
- [ ] `static/cameras.html` — `movensys_vlm`에서 이식
- [ ] 메인 UI 우측 하단 카메라 썸네일, "No stream" 폴백 (§9)
- [ ] `ros2_node.py` Isaac card-spawn publisher — `${MONOPOLY_ISAAC_TOPIC_CARD_SPAWN}` (§11.5)
- [ ] 카드 draw 시 publish 훅 (§7.3.6)
- [ ] Isaac 구독자 없을 때 publish 무시 동작 검증

### 16.6 M5 — Robot adapter integration
- [ ] `adapters/robot.py` httpx 클라이언트 — `/dice/roll`, `/horse/move`, `/base_position` (§8.3)
- [ ] Fire-and-forget `/horse/move` — 게임 엔진 비차단 (§8.3)
- [ ] `/api/robot/{base_position,roll_dice,move_piece}` 프록시 라우트 (§5.7)
- [ ] `ROBOT_SERVICE_URL` live 모드 시 `/api/robot/health` → `{mode:"live"}`
- [ ] `robot_error` WS 이벤트 발행 (로봇 실패 시)
- [ ] `dice_source="robot"` 설정 시 `/dice/request`가 로봇 호출로 라우팅
- [ ] 실제 로봇 서비스와 수동 통합 테스트

### 16.7 M6 — Whisper STT integration
- [ ] 브라우저 push-to-talk 버튼 (`MediaRecorder` WAV/Opus) (§8.1)
- [ ] `adapters/stt.py` — multipart 업로드 클라이언트
- [ ] `POST /api/stt` 어댑터 라우트
- [ ] `POST /api/utterance/submit {text}` 내부 라우트
- [ ] `POST /api/debug/inject_utterance` (§5.10)
- [ ] UI: stub 모드에서 텍스트 입력창 fallback
- [ ] 언어 hint 처리 (ko/en)

### 16.8 M7 — Gemma 4 LLM integration
- [ ] `adapters/llm.py` — `POST /infer` 클라이언트 (§8.2)
- [ ] Intent dispatcher — 12개 intent → 엔드포인트 매핑 (§8.2)
- [ ] Context builder (fsm, turn, pending_decision, balance, board_id)
- [ ] `GET /api/board/snapshot` → `{image_b64, prompt_hint}` (§5.9)
- [ ] VLM path: `image_b64` 포함 요청 (`board_query` intent)
- [ ] `decision_source: "gemma"` WS 태깅
- [ ] Low confidence (< 0.5) 시 greedy로 fallback
- [ ] `POST /api/debug/simulate_llm_intent` (§5.10)

### 16.9 M8 — (Optional) Chance art + Isaac
- [ ] Chance/CC 카드 SVG 자체 제작 (텍스트 기반) (§9.1)
- [ ] 카드 모달에 이미지 렌더 (현재는 텍스트만)
- [ ] Isaac 카드 소환 payload 필드 최종 확정 (§16 Open Q. 4)
- [ ] Isaac Sim 팀과 end-to-end 소환 테스트

### 16.10 Cross-cutting (마일스톤 독립, 병행 가능)
- [ ] `game/persistence.py` — `GameState` JSON save/load (5초 주기) (§11.3)
- [ ] Prometheus `/metrics` — `fsm_transitions_total` 등 (§11.4)
- [ ] README.md (개발자 온보딩) — 현재는 PRD가 유일 문서
- [ ] Production Dockerfile — `MONOPOLY_DEBUG_ROUTES=false` 기본
- [ ] UI 회귀 Playwright 워크플로 (별도 CI YAML) (§13)

---

## 17. Open Questions

locked spec 이 아닌 결정 대기 항목. (§1.1에서 확정된 7건은 제거됨)

1. **외부 FastAPI 3종 request/response 스펙 최종 합의**: §8의 제안안을 Whisper·Gemma·Robot 각 팀과 확정. 특히 Gemma intent 스키마(§8.2) 수용 여부.
2. **플레이어 색상**: user=빨강(`#E53935`) / robot=파랑(`#1E88E5`) 기본. `/game/config`로 런타임 변경 가능하지만 기본값 확정 필요.
3. **Board 1 메인 보드 이미지 재제작 여부**: 현재는 원본 PNG 내부 사용. 외부 배포 시 SVG로 재제작 필요.
4. **Isaac Sim 토픽 스키마**: `${MONOPOLY_ISAAC_TOPIC_CARD_SPAWN}` 페이로드 필드(§11.5)를 Isaac 팀과 합의.

---

## 18. Appendix — Typical Turn Flow (reference)

실제 턴이 어떻게 흘러가는지 **참고용 narrative**. 스펙은 §5-§7.

1. "게임 시작" → `POST /game/start {board:"2"}` (AI 또는 수동 버튼)
2. Robot base pose (선택) → `POST /robot/base_position` (실패해도 진행)
3. "주사위 굴려" → `POST /dice/request` → 값 확보 → `POST /dice/submit`
4. Fire-and-forget `POST /robot/move_piece`, 동시에 `POST /move/apply`로 상태 갱신
5. `rules.resolve_tile()` 자동 실행:
   - 빈 property → `event: property_card_shown` → 결정 엔드포인트 대기
   - 상대 property → 임대료 즉시 차감
   - Chance/CC → 카드 뽑고 효과 적용
   - Board 2 특수 타일 (jail/tax/railroad/utility) → 해당 규칙
6. `POST /game/end_turn` → 턴 전환
7. 파산 또는 승리 조건 충족 시 `fsm → GAME_OVER`
