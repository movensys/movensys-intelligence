# PRD — movensys-monopoly

> **Document type:** Product Requirements Document (PRD) — 기술 상세
> **Owner:** sjhwang@movensys.com
> **Status:** Draft v0.1 (2026-04-23)
> **Sibling package:** `movensys_vlm` (동일 리포 `movensys-intelligence/`)

---

## 0. 개요 (Overview)

`movensys-monopoly`는 **사용자 1명 + 로봇 1대(manipulator)** 가 실물 보드로 모노폴리를 플레이하는 통합 데모 패키지다.
`movensys_vlm`과 동일한 형식(ROS 2 + FastAPI + Docker Compose)으로 제공되며, 게임 상태·보드 시각화·돈 시각화·property 관리를 담당하는 단일 FastAPI 서비스가 핵심이다.

### 0.1 설계 원칙 — "Headless / Manual 모드 우선"

본 패키지는 **AI·로봇이 전혀 없이도 Board 1/2/3의 모든 규칙이 동작**하도록 설계한다.
외부 의존성(AI·로봇)은 "게임 엔진 입력 포트"에 꽂는 **선택적 어댑터**이며, 게임 엔진 자체는 이들과 독립적으로 구현·검증된다.

구조적으로 세 계층으로 분리한다.

```
┌────────────────────┐   ┌─────────────────────┐   ┌────────────────────┐
│  Intent Source     │──▶│   Game Engine       │──▶│  Physical Executor  │
│  (의도 입력)        │   │   (순수 게임 로직)    │   │  (실세계 동작)       │
│                    │   │                     │   │                    │
│ · Whisper+Gemma    │   │ · 규칙/상태/돈/      │   │ · Dice/Horse       │
│   (외부)           │   │   property/FSM     │   │   pick-and-place   │
│ · 수동 UI 버튼      │   │ · Board 1/2/3 전부  │   │   (외부)           │
│   (내장, 항상 가능) │   │   [IMPL]           │   │ · Headless (No-op)│
└────────────────────┘   └─────────────────────┘   └────────────────────┘
```

- **Intent Source**: Whisper→Gemma 경로가 **없어도** UI의 수동 컨트롤로 동일 REST 엔드포인트를 때릴 수 있다. 즉 수동 모드가 항상 1급 시민이다.
- **Game Engine**: 본 패키지의 `game/*` 모듈. 외부 호출 없이 단독으로 pytest로 전수 검증 가능.
- **Physical Executor**: 로봇 서비스가 없어도 게임 상태는 **항상 진행된다**. 물리 동작은 "fire-and-forget" 요청이고, 게임 엔진은 그 완료를 기다리지 않는다. Headless 모드에서는 해당 호출을 no-op으로 대체.

### 0.2 외부 의존 모듈 (정확한 목록)

본 패키지 **외부에서 제공받는** FastAPI 서비스는 다음 **3개뿐**이다.

| # | 서비스 | 인터페이스 형태 | 본 패키지에서의 역할 | 부재 시 대체 |
|---|---|---|---|---|
| 1 | **Whisper AI on FastAPI** | HTTP `POST /stt` `{audio}` → `{text}` | 사용자 발화 → 텍스트 | UI의 텍스트 입력창 (`/api/debug/inject_utterance`) |
| 2 | **Gemma 4 on FastAPI** | HTTP `POST /infer` `{text \| image_b64, context}` → `{intent, args}` | 텍스트·보드 이미지 → 게임 액션 의도 | UI의 수동 버튼이 `/api/...` 직접 호출 |
| 3 | **Dice & Horse Pick-and-Place on FastAPI** | HTTP `POST /dice/roll` → `{value}`, `POST /horse/move` `{player_id, from_tile, to_tile}` → `{ok}` | 실제 주사위 굴림·말 이동 | Headless: 서버가 값 주입, UI가 말 이동 애니메이션만 재생 |

**`movensys_vlm`의 MoveIt2를 직접 호출하지 않는다.** 로봇과의 물리적 접점은 위 3번 서비스로만 수행한다(해당 서비스가 내부적으로 MoveIt2를 쓰든 말든 본 패키지는 관여하지 않음).

### 0.3 구성요소 맵

| # | 구성요소 | 역할 | 본 패키지 범위 |
|---|---|---|---|
| 1 | **STT (Whisper on FastAPI)** | 사용자 음성 → 텍스트 | 외부 — `POST /stt` 어댑터만 정의, 없으면 수동 입력 |
| 2 | **Gemma 4 on FastAPI** | 자연어/이미지 → 의도 | 외부 — `POST /infer` 어댑터만 정의, 없으면 수동 버튼 |
| 3 | **Dice/Horse Pick-and-Place on FastAPI** | 주사위 굴림·말 이동 물리 실행 | 외부 — fire-and-forget 클라이언트만 정의, 없으면 no-op |
| 4 | **Mounted Camera (ROS 2)** | `image_top` / `image_hand` 토픽 구독 | `movensys_vlm` 스트림 프록시 재사용 (있으면 표시, 없어도 게임 진행) |
| 5 | **Isaac Sim (선택)** | 물리 시뮬레이션, chance 카드 소환 | 외부, 완전 선택 사양 |
| 6 | **movensys-monopoly FastAPI** | 게임 규칙 엔진·상태·UI | **본 패키지의 주 구현 — AI/로봇 없이도 완전 동작** |

> **구현 우선순위 표기:** 본 문서의 각 섹션은 말미에 `[IMPL]`(자체 구현 가능), `[EXT]`(외부 FastAPI 의존), `[STUB]`(스텁/목 처리로 먼저 배선) 태그를 둔다.
> **원칙:** 외부 의존 항목에는 **반드시 `[IMPL]` 수동 대체 경로가 병행**된다.

---

## 1. 디렉토리 구조 & 포맷

`movensys_vlm`의 구조를 그대로 따른다.

```
movensys-monopoly/
├── doc/
│   ├── PRD.md              ← 본 문서
│   ├── PRD_easy.md         ← 비개발자 대상 요약본
│   └── running.md          ← 실행법 (추후)
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── entrypoint.sh
├── static/
│   ├── index.html          ← 메인 보드 UI (Board 1/2/3 전환)
│   ├── cameras.html        ← 마운트 카메라 뷰 (movensys_vlm에서 이식)
│   └── assets/
│       ├── boards/
│       │   ├── monopoly_short.png   ← ~/Downloads/Monopoly_short.png
│       │   ├── monopoly_origin.jpg  ← ~/Downloads/Monopoly_origin.jpg
│       │   └── board3_blank.svg     ← 12-tile 빈 보드 (자체 생성)
│       ├── property_cards/          ← 각 property SVG/PNG
│       └── chance_cards/            ← chance 카드 이미지 (수집 결과)
├── main.py                 ← FastAPI 엔트리
├── router.py               ← 게임/보드/돈/property/카메라 REST & WS
├── ros2_node.py            ← ROS 2 브릿지 (카메라 + MoveIt2 클라이언트)
├── game/
│   ├── __init__.py
│   ├── state.py            ← GameState 싱글턴 (보드/플레이어/턴)
│   ├── boards.py           ← Board 1/2/3 정의 로더
│   ├── properties.py       ← property 카드 스키마 & 가격표
│   ├── chance.py           ← chance 카드 데크
│   ├── rules.py            ← 이동·지불·건물·파산 규칙 엔진
│   └── persistence.py      ← 게임 세이브/로드 (JSON, 선택)
└── requirements.txt
```

### 1.1 Docker 실행

`movensys_vlm`과 동일 방식.

```bash
cd ~/workspaces/movensys-intelligence/movensys-monopoly/docker
docker compose down
docker compose build
docker compose up
```

- `docker-compose.yml` 환경변수: `ROS_DISTRO`, `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`, `MOVENSYS_MANIPULATOR_PACKAGES`
- 포트: `8000` (FastAPI)
- `network_mode: host` — ROS 2 DDS 디스커버리 공유

---

## 2. 보드 (Boards)

### 2.1 Board 1 — `Monopoly_short.png` 기반 단축 보드

- 경로: `static/assets/boards/monopoly_short.png`
- 타일 수: 원본 이미지 분석 후 확정 (예상 20칸 내외)
- 기능: property 구매/건물/임대료/chance 전부 지원
- 목적: **풀 게임 규칙의 짧은 플레이 세션용** (시연에 적합) [IMPL]

### 2.2 Board 2 — `Monopoly_origin.jpg` 기반 표준 보드

- 경로: `static/assets/boards/monopoly_origin.jpg`
- 타일 수: 40칸 (표준 모노폴리)
- 기능: Board 1 전부 + 감옥/세금/역(railroad)/유틸리티 등 **원본 규칙 전부** 지원 [IMPL]
- **중요:** Board 2의 모든 규칙(감옥 FSM·역 임대료·유틸리티 임대료·세금·색상그룹 독점·커뮤니티체스트 덱)은 **순수 게임 로직**이므로 AI·로봇 없이도 100% 구현·테스트 가능하다. 외부 의존은 "입력(발화)"과 "물리 실행(집기·옮기기)" 계층에서만 발생하며, 이들은 모두 수동 UI/스텁으로 대체 가능하다.
- 세부 규칙은 §10-4-B 참조.

### 2.3 Board 3 — 12칸 빈 보드 (스모크 테스트용)

- 경로: `static/assets/boards/board3_blank.svg` (자체 생성)
- 타일 수: **12개 동일한 빈 타일** + START 마커
- 규칙:
  - 돈/Property/Chance **없음**
  - 주사위 굴림 → 말 이동 → 한 바퀴(12칸)를 먼저 돈 쪽이 **승리**
  - 승리 조건 이외 상태 전이는 없음
- 목적: **카메라·매니퓰레이터·FastAPI 말 업데이트 루프만 검증**하는 최소 파이프라인 [IMPL]

### 2.4 Property card / Chance card 에셋 수집

- **property card 디자인 원본**: Hasbro의 공식 카드 아트는 저작권이 있으므로 상용 배포용으로는 재사용이 어렵다. 개발·시연 한정으로는 다음을 검토한다.
  1. **오픈소스/팬메이드 리메이크**: `github.com/search?q=monopoly+cards+svg` 계열의 MIT/CC 라이선스 에셋 탐색
  2. **자체 제작**: 색상 스트라이프 + 가격표만 있는 단순 SVG (`assets/property_cards/*.svg`)
  3. **위키미디어 공용 (Wikimedia Commons)**: 저작권이 만료되었거나 CC-BY 라이선스인 모노폴리 관련 이미지
- **chance card**: 위와 동일. chance의 경우 **카드의 "지시문 텍스트"** 가 핵심이므로, 아트가 없더라도 JSON 데크(`game/chance.py`)만으로 규칙은 동작한다.
- 수집 결과는 별도 PR에서 `static/assets/property_cards/`, `static/assets/chance_cards/` 밑에 정리. **PRD 레벨에서는 "수집 Task"로 남긴다.** [STUB → IMPL]

---

## 3. 돈 (Money)

### 3.1 데이터 모델

```python
# game/state.py
class PlayerMoney:
    player_id: Literal["user", "robot"]
    balance: int              # 정수 단위 (달러)
    history: list[Transaction]  # (+/- 금액, 사유, 타임스탬프)
```

### 3.2 초기 금액

- Board 1: 1,000 (단축 플레이 → 적은 시드)
- Board 2: 1,500 (표준 모노폴리 규칙)
- Board 3: N/A

### 3.3 FastAPI 시각화

- **항상 표시**: 화면 상단 바에 두 플레이어의 잔액을 **지폐 아이콘 스택 + 숫자**로 동시 표시
- **변동 모션** (required for 10-1-3-1-2):
  - 감소: 지폐가 플레이어 쪽에서 떨어지며 페이드아웃 (CSS animation, ~600ms)
  - 증가: 지폐가 플레이어 쪽으로 날아들어오며 카운터 숫자 카운트업
  - 구현: `static/index.html` 내 `<money-widget>` 커스텀 요소, WS `/api/stream/money` 이벤트 수신
- **이력 패널**: 사이드 토글로 최근 10개 트랜잭션 표시 (원인: "build", "rent paid to robot", "chance: +200" 등)

### 3.4 API

| Endpoint | Method | 설명 |
|---|---|---|
| `/api/money` | GET | 현재 두 플레이어 잔액 스냅샷 |
| `/api/money/{player_id}` | GET | 단일 플레이어 상세 + history |
| `/api/stream/money` | WS | 잔액 변경 시마다 delta push |
| `/api/money/transfer` | POST (internal) | 플레이어 간 이체 (payer, payee, amount, reason) |

`/api/money/transfer`는 **규칙 엔진(`game/rules.py`)에서만 호출**하는 내부 경로다. 외부(Gemma 4, 수동 UI)에서는 규칙이 호출되는 상위 엔드포인트(예: `/api/properties/{id}/decide`, `/api/effects/pay`)를 경유해야 한다.

---

## 4. Property

### 4.1 데이터 모델

```python
# game/properties.py
class PropertyCard:
    id: str                     # "board1:mediterranean"
    tile_index: int             # 보드에서의 칸 번호
    name: str
    color_group: str            # "brown", "lightblue", ...
    price_buy: int              # 구매가 (여기서는 "구매" 개념이 없으면 None)
    price_building: int         # 건물 1채당 비용
    rent: list[int]             # [기본, 집1, 집2, 집3, 집4, 호텔]
    image: str                  # 카드 이미지 경로
    owner: Literal["user", "robot", None]
    houses: int                 # 0..4
    has_hotel: bool
    mortgaged: bool
```

### 4.2 소유 property UI

- 화면 **좌/우 사이드바**에 각각 user/robot이 소유한 property를 **색상 그룹별로 묶어** 썸네일로 나열
- 썸네일 클릭 → 모달로 풀 카드 표시 (§4.3 참조)
- 건물 수는 썸네일 위에 작은 아이콘(집 🏠 / 호텔 🏨)으로 오버레이 (이모지 사용은 요청 시에만 — 기본은 SVG 아이콘)

### 4.3 Property card 모달

- 상단: 색상 스트라이프
- 중단: 가격 / 건물별 임대료 표 / 현재 건물 수
- 하단 (자기 턴일 때만):
  - **"건물 짓기" 버튼** (Gemma 4가 호출하는 것과 동일 엔드포인트를 호출하는 수동 트리거 — 항상 활성화)
  - "상태" 배지: "구매 가능" / "내 소유" / "상대 소유 (임대료 N)" / "저당"

### 4.4 API

| Endpoint | Method | 설명 |
|---|---|---|
| `/api/properties` | GET | 전체 property 상태 |
| `/api/properties/{id}` | GET | 단일 카드 |
| `/api/properties/{id}/buy` | POST | 매입 (규칙: 소유주 없음 + 잔액 충분) |
| `/api/properties/{id}/build` | POST | `{houses: +1}` 또는 `{hotel: true}` — §5.1.3 흐름 |
| `/api/properties/{id}/mortgage` | POST | 저당 (§5.2 파산 직전) |
| `/api/properties/{id}/sell_building` | POST | 건물 1채 매각 → 절반가 회수 |
| `/api/stream/properties` | WS | property 상태 변경 스트림 |

---

## 5. 게임 플로우 (Game Flow)

> **범례:** `[IMPL]`=본 패키지에서 자체 구현 / `[EXT:stt]`=Whisper FastAPI 의존 / `[EXT:llm]`=Gemma 4 FastAPI 의존 / `[EXT:robot]`=Dice/Horse pick-and-place FastAPI 의존 / `[STUB]`=스텁 선 배선.
> **모든 `[EXT:*]` 단계는 수동 UI로 동일 엔드포인트를 호출할 수 있는 `[IMPL]` 경로가 병존한다.**

### Step 1 — 게임 시작 트리거
- **AI 모드 `[EXT:stt+llm]`**: 사용자 발화 "게임 시작할게" → Whisper(`POST /stt`) → Gemma(`POST /infer`) → 본 패키지 `/api/game/start` 호출
- **수동 모드 `[IMPL]`**: UI "게임 시작" 버튼이 `/api/game/start` 직접 호출
- **엔드포인트:** `POST /api/game/start`, Body: `{board: "1" | "2" | "3"}`
- 동작: `GameState` 초기화, 턴을 user로 설정, `/api/stream/game` broadcast

### Step 2 — 로봇을 베이스 자세로 (선택)
- **로봇 모드 `[EXT:robot]`**: `POST {robot_svc}/base_position` 호출 (로봇 서비스가 제공하는 경우)
- **Headless 모드 `[IMPL]`**: no-op. 게임 상태 전이는 독립적으로 진행.
- **엔드포인트:** `POST /api/robot/base_position` — 내부적으로 외부 로봇 FastAPI로 전달하되, 응답 실패/타임아웃 시에도 게임 진행은 막지 않는다.

### Step 3 — 주사위 굴림 요청
- **AI 모드 `[EXT:stt+llm]`**: 사용자 "주사위 굴려" → Whisper → Gemma → `/api/dice/request`
- **수동 모드 `[IMPL]`**: UI "주사위 굴리기" 버튼이 `/api/dice/request` 호출
- 본 패키지는 설정된 `dice_source`에 따라:
  - `robot`: 외부 로봇 FastAPI `POST {robot_svc}/dice/roll` → 응답 `{value}` 수신 → `/api/dice/submit` 내부 호출
  - `manual`: UI에서 숫자 직접 입력 (1~6)
  - `rng`: 서버가 `random.randint(1,6)` 반환 (Headless 개발 모드 기본값)

### Step 4 — 주사위 값 등록 `[IMPL]`
- **엔드포인트:** `POST /api/dice/submit`, Body: `{value: int, source: "robot" | "manual" | "rng"}` (1~6)
- 동작: 현재 턴 플레이어의 `pending_dice` 설정 → FSM을 `MOVING` 으로 전이

### Step 5 — 말 이동 (물리) (선택)
- **로봇 모드 `[EXT:robot]`**: `POST {robot_svc}/horse/move` `{player_id, from_tile, to_tile}` fire-and-forget
- **Headless 모드 `[IMPL]`**: no-op
- 어느 모드든 Step 6의 게임 상태 갱신은 **로봇 응답을 기다리지 않고** 즉시 진행된다.

### Step 6 — FastAPI 보드 업데이트 `[IMPL]`
- Endpoint: `POST /api/move/apply`
  - Body: `{player_id, from_tile, to_tile}`
  - 검증: `(from_tile + dice_value) mod board_size == to_tile`
  - 실패 시 409 Conflict (비전 오판 가능성)
  - 성공 시 `GameState.positions` 갱신 → `/api/stream/board` broadcast
- UI: 말 아이콘이 타일 간 슬라이드 애니메이션 (~400ms)

#### 6-A. Board 3 전용 승리 판정 `[IMPL]`
- Board 3에서 `to_tile`이 **이전 위치보다 앞서며 START를 넘어섰다면** 승자로 설정
- `/api/game/winner` GET → `{winner: "user" | "robot" | null}`

### Step 7 — 보드 상태 판독 (선택)
- **AI 모드 `[EXT:llm]`**: 사용자 "보드 상태 알려줘" → Gemma에 `/api/board/snapshot` 이미지 + 힌트 전달 → Gemma가 도착 칸 판독 → 의도 라우팅
- **수동/서버 모드 `[IMPL]`**: 본 패키지는 `GameState`를 **단일 진실 원천**으로 취급하므로 VLM 판독 없이도 `to_tile`을 이미 알고 있다. Step 8(타일 처리)을 서버가 직접 트리거한다.
- `GET /api/board/snapshot` → `{board_image_b64, expected_turn, prompt_hint}`는 AI 모드 전용이며, 없어도 게임 진행 가능.

### Step 8 — 도착 타일에 따른 분기 처리 `[IMPL]`
Step 6의 `/api/move/apply`가 성공하면 서버는 즉시 `rules.py`의 `resolve_tile(player, to_tile)`을 호출해 도착 타일 종류에 따라 분기:
- 빈 property: §10-1 흐름
- 상대방 property: §10-2 (임대료 즉시 처리)
- Chance/Community Chest 타일: §10-3
- Board 2 특수 타일(감옥행/세금/유틸리티/역/시작점): §10-4-B

이 분기는 **전부 서버 측 결정론적 로직**이며 AI 판독을 기다리지 않는다.

### Step 9 — 마운트 카메라 표시 (선택) `[IMPL]`
- `movensys_vlm`의 카메라 구독 로직을 이식 — 게임 진행과 **완전 독립**
  - `/image_top/rgb`, `/image_top/depth`, `/image_hand/rgb`, `/image_hand/depth`
  - WS 스트림 `/api/stream/image_top/rgb` 등
- UI: `static/cameras.html` 이식, 메인 화면 우측 하단에 썸네일
- 카메라 토픽이 없어도 해당 위젯은 "No stream" 플레이스홀더만 표시되고 게임은 정상 진행

---

### 10-1. 빈 property(건물 없음)에 도착 시 [IMPL]
- 서버 `rules.py`가 to_tile의 상태를 분류:
  - **소유주 없음 + 구매 가능**: `/api/stream/game`으로 `event: "property_card_shown"` 푸시 → UI가 모달로 property card 렌더링
  - 동시에 §10-1-1 검사

### 10-1-1. 건물 짓기 위한 최소 자금 보유 여부 [IMPL]
- 최소 자금 = `price_buy + price_building` (구매 + 집 1채)
- 보유액 < 최소 자금 → `event: "insufficient_funds_for_property"` 푸시 → **10-1 건너뜀, 다음 턴으로**

### 10-1-2. "건물 지을래? 얼마나?" 질문 단계
- UI가 "대답해주세요" 상태 배지 표시
- **AI 모드 `[EXT:stt+llm]`**: Whisper → Gemma 4 루트
- **수동 모드 `[IMPL]`**: 모달에 "구매 스킵" / "구매만" / "구매 + 건물 N채" 버튼이 항상 표시되어 즉시 결정 가능

### 10-1-3. 의도 파싱 → 결정 실행 `[IMPL]`
- 최종 결정은 AI든 수동이든 **동일 엔드포인트**로 수렴:
  - `POST /api/properties/{id}/decide` — Body: `{action: "skip"} | {action: "buy"} | {action: "build", house_count: int}`
- 서버가 §10-1-3-1 검사

### 10-1-3-1. 실제 건설 가능성 검증 [IMPL]
- 조건: (잔액 ≥ `price_buy + house_count * price_building`) && (같은 color_group 규칙 준수)

#### 10-1-3-1-1. 불가 — 돈 부족 [IMPL]
- 응답: `409 Conflict`, UI에 "자금 부족으로 건설할 수 없습니다" 모달
- 상태: `waiting_for_decision` 유지 → Gemma 4가 다시 10-1-3으로 돌아오도록 `/api/game/next_prompt` hint 갱신

#### 10-1-3-1-2. 가능 [IMPL]
- 트랜잭션: `money.transfer(from=player, to=bank, amount=cost, reason="build")`
- UI: 돈 감소 모션 (§3.3)
- → 10-1-4

### 10-1-4. FastAPI 상에 건물 표시 [IMPL]
- 기본 동작: **자신이 살 수 있는 가장 비싼 건물**을 자동 선택 (사용자 요청)
  - 예: 잔액이 허락하면 호텔 > 집 4 > 집 3 > ...
- **단, 10-1-3에서 `house_count`가 명시되면 그 값을 따른다** (미래 구현 대비 API 시그니처 유지)
- UI: 타일 위에 집/호텔 아이콘 누적, property 썸네일 카운트 +1

---

### 10-2. 상대방 땅에 도착 → 임대료 지불 [IMPL]
- `rules.py`:
  1. `to_tile`의 owner가 상대방이면 `rent = property.rent[houses_or_hotel_level]`
  2. 지불자 잔액 ≥ rent → `money.transfer(payer, payee, rent, "rent")`, UI 감소/증가 모션
  3. 잔액 < rent:
     a. 지불자 소유 property 중 건물 있는 것부터 **자동 매각 후보 리스트**를 UI에 제시 (`event: "auto_liquidation_prompt"`)
     b. 매각 시 건물 매각 절반가 + (필요 시) 저당 50% → 잔액에 가산
     c. 그래도 부족 + 남은 자산 없음 → `event: "bankruptcy"`, 패배 처리, 게임 종료
- UI: 건물 사라지는 애니메이션 (§4.2 썸네일 뱃지 감소)

---

### 10-3. Chance 타일 도착 `[IMPL]`
- `game/chance.py`에 **JSON 카드 데크** 보유 (예: `{"id": "advance_to_go", "text": "출발로 전진. $200 획득", "effect": {type: "move_to_tile", tile_index: 0, collect_on_pass: true}}`)
- 서버는 랜덤 카드를 pop → **카드 효과를 서버가 즉시 적용** (구조화된 `effect` 스키마 사용)
- `/api/stream/game`에 `event: "chance_card_drawn"` + 효과 적용 결과 푸시 → UI가 카드 이미지(있으면) + 텍스트 표시
- **주의:** 카드 효과는 `rules.py`가 결정론적으로 처리한다. Gemma 4가 텍스트를 "해석"할 필요 없음 — 카드 JSON의 `effect` 필드가 이미 구조화돼 있다.
- 제공 effect endpoints (Chance·Community Chest 공용, 카드 JSON에서 참조되는 액션들을 수동으로도 호출 가능):
  - `POST /api/effects/move_to_tile`
  - `POST /api/effects/collect`
  - `POST /api/effects/pay`
  - `POST /api/effects/go_to_jail` (Board 2 한정)
  - `POST /api/effects/grant_jail_free_card` (Board 2 한정)
  - … 등
- **Isaac Sim 카드 소환 (선택 `[EXT]`)**: `chance_card_drawn` 이벤트를 받아 외부 Isaac Sim이 물리 카드를 소환할 수 있다. 본 패키지와 무관하게 동작.

---

### 10-4. Board 1/2 별 추가 규칙 — 제안 (요청하신 확장 지점)

**내가 제안할 테니 컨펌을 받는다**는 섹션 10-4에 대한 제안서. 최종 결정은 다음 리뷰에서.

#### 10-4-A. Board 1 (짧은 보드) 제안 확장
- **Short Chance** 카드 풀: 원본보다 가벼운 8~10장 (이동/돈 증감 위주)
- **세금 타일 1칸** (일정 금액 지불)
- **"파킹" 타일 1칸** (아무 일 없음, 휴식)
- **출발(START) 보너스**: 통과 시 +100
- 구매 가능한 property 개수: 8~10개 (2~3개 color group)

#### 10-4-B. Board 2 (원본 표준) 확장 — **전부 `[IMPL]` (AI/로봇 불필요)**

아래 모든 항목은 **순수 게임 로직**으로 구현되며, pytest로 단독 검증 가능하고 UI의 수동 버튼으로 재현 가능하다.
외부 FastAPI 3종(Whisper/Gemma/Dice·Horse)이 전부 없어도 Board 2는 완전 동작한다.

##### 10-4-B-1. 감옥 (Jail) `[IMPL]`
- **상태 필드 (`GameState.players[pid]`):**
  - `in_jail: bool`, `jail_turns_left: int` (0~3), `has_jail_free_card: bool`
- **투옥 트리거:**
  - "Go to Jail" 타일(30번) 도착
  - 한 턴에 주사위 더블 3연속 (3번째 더블 시 즉시)
  - Chance/Community Chest 카드 "Go to Jail"
- **탈출 조건 (턴마다 1개 선택):**
  1. 주사위 더블 → 해당 값만큼 이동, `in_jail=false`
  2. $50 지불 → `in_jail=false`, 주사위 굴림 후 이동
  3. `has_jail_free_card=true` → 카드 소비, `in_jail=false`
  4. 3턴째 실패 → 자동 $50 지불, `in_jail=false`
- **엔드포인트:** `POST /api/jail/attempt_exit` Body: `{method: "dice" | "pay" | "card"}`
- **UI:** 감옥 타일에 감옥 아이콘 + `jail_turns_left` 카운터. 수동 UI는 세 버튼 제공.

##### 10-4-B-2. 역(Railroad) 4곳 `[IMPL]`
- 타일 인덱스: 5(Reading), 15(Pennsylvania), 25(B&O), 35(Short Line)
- 구매가 $200, 저당가 $100
- **임대료 = $25 × 2^(owner가 보유한 역 개수 - 1)** → 1개 $25, 2개 $50, 3개 $100, 4개 $200
- `PropertyCard.kind = "railroad"` 도입, `rent` 필드 대신 런타임 계산
- `game/rules.py`의 `compute_rent(property, owner_portfolio)`가 kind별 분기 처리

##### 10-4-B-3. 유틸리티(Utility) 2곳 `[IMPL]`
- 타일 인덱스: 12(Electric Company), 28(Water Works)
- 구매가 $150
- **임대료 = 직전 주사위 합계 × 계수**: 1개 소유 시 ×4, 2개 전부 소유 시 ×10
- `PropertyCard.kind = "utility"`. `compute_rent`가 `last_dice_sum`을 참조.

##### 10-4-B-4. 세금 타일 `[IMPL]`
- 소득세(타일 4): **$200 또는 총자산의 10% 중 선택** (Board 2는 고정 $200으로 단순화 옵션 제공, 설정 토글)
- 사치세(타일 38): $100 고정
- `game/rules.py`의 `handle_tax_tile(player, tile)` — 잔액에서 차감, history에 "tax" 기록

##### 10-4-B-5. 색상 그룹 독점 (Monopoly Bonus) `[IMPL]`
- `PropertyCard.color_group` 기준, 한 플레이어가 그룹의 모든 타일 소유 시 `is_monopoly(group, owner)` = true
- **건물 없는 상태 임대료 × 2**
- **건물 건설 가능 조건**: 해당 그룹 독점 상태여야만 `/api/properties/{id}/build` 허용
- **균등 건설 규칙**: 같은 그룹 내 타일들의 건물 수 차이가 1 이하여야 한다 (원본 룰). `rules.py`가 검증.

##### 10-4-B-6. Community Chest 덱 `[IMPL]`
- `game/community_chest.py` — chance와 **분리된 JSON 덱** (16장 기본 세트)
- 타일 인덱스: 2, 17, 33
- 동작 구조는 chance(§10-3)와 동일, 단 효과셋이 다름 (예: "Bank error in your favor — collect $200")
- `POST /api/effects/*` 는 chance/community chest 공용 (효과 타입이 동일하면 재사용)
- "Get Out of Jail Free" 카드는 이 덱에도 1장 존재 → `has_jail_free_card` 부여, 사용 시 덱 하단으로 반환

##### 10-4-B-7. 시작점(START) 보너스 `[IMPL]`
- 시작점을 **통과**: +$200, **정확히 도착**: +$200 (Board 2 표준; 원본 룰에 "Landing on GO = $400" 변형은 설정 토글)
- `rules.py`의 이동 처리에서 `from_tile > to_tile` (wrap)일 때 지급

##### 10-4-B-8. 저당 (Mortgage) `[IMPL]`
- 저당가 = 구매가의 50%
- 저당된 property는 임대료 수취 불가 (임대료 = 0)
- 저당 해제 시 저당가 × 1.1 지불
- 엔드포인트: `POST /api/properties/{id}/mortgage`, `POST /api/properties/{id}/unmortgage`

##### 10-4-B-9. 경매 (Auction) — **옵션, 기본 OFF**
- 원본 룰: 플레이어가 property 구매 거절 시 경매 진행
- 1인 vs 로봇 구도에서 경매는 UX가 복잡하므로 **기본 비활성화**, `config.auctions_enabled: false`
- 활성화 시에만 `POST /api/auction/start`, `/api/auction/bid` 경로 추가

---

**구현 검증 방법:** 위 모든 항목은 `tests/board2/test_*.py`에서 `GameState`를 조작해 검증한다. AI/로봇 FastAPI를 전혀 기동하지 않은 상태에서 `pytest` 전수 통과가 "Board 2 완성"의 정의다.

---

## 6. 상태 기계 (FSM)

```
        ┌──────────────┐
        │     IDLE     │  ← /api/game/start 이전
        └──────┬───────┘
               │ start
               ▼
        ┌──────────────┐    base pos
        │ TURN_START   │─────────────┐
        └──────┬───────┘              │
               │ dice submitted       │
               ▼                       │
        ┌──────────────┐              │
        │  MOVING      │              │
        └──────┬───────┘              │
               │ move applied         │
               ▼                       │
        ┌──────────────┐              │
        │ RESOLVE_TILE │              │
        └──┬────┬────┬─┘              │
           │    │    │                │
     empty │  own │ opp│             │
    property│ rop │erty│              │
           ▼    ▼    ▼                │
      AWAIT    END   PAY_RENT         │
      DECISION TURN   │               │
        │          (bank  ─►  LOSS or │
        │ decide   ruptcy?)  END_TURN─┘
        ▼
      BUILD_OR_SKIP ─► END_TURN
```

- 각 상태 전이는 `/api/stream/game`에 `{event, from_state, to_state}` 푸시
- 상태는 `game/state.py`의 `GameState.fsm` 필드로 노출

---

## 7. REST/WS 엔드포인트 요약

### 7.1 Game control
| Method | Path | 용도 |
|---|---|---|
| POST | `/api/game/start` | 게임 시작 (board 선택) |
| POST | `/api/game/end_turn` | 턴 종료 |
| GET  | `/api/game/state` | 전체 스냅샷 |
| GET  | `/api/game/winner` | 승자 체크 (Board 3 필수) |
| GET  | `/api/game/next_prompt` | Gemma 4가 다음 질문할 텍스트 힌트 |
| POST | `/api/game/config` | `dice_source`(robot/manual/rng), `auctions_enabled`, 플레이어 색상 등 런타임 설정 |
| WS   | `/api/stream/game` | FSM 이벤트 |

### 7.2 Dice & movement
| POST | `/api/dice/request` | 주사위 굴림 요청 — `dice_source`에 따라 로봇/RNG 분기 |
| POST | `/api/dice/submit` | 주사위 값 등록 (수동·로봇·RNG 공용 입구) |
| POST | `/api/move/apply` | 말 이동 적용 |
| WS   | `/api/stream/board` | 말 위치 스트림 |

### 7.2-A Adapters (외부 FastAPI 3종 어댑터) `[EXT]`
> 본 패키지 **내부**에서 외부 서비스를 감싸는 얇은 어댑터 계층. URL 환경변수만 바꾸면 스텁으로 전환 가능.

| Adapter | 환경변수 | 외부 경로 | 본 패키지 내부 호출점 |
|---|---|---|---|
| Whisper STT | `STT_SERVICE_URL` | `POST /stt` | `POST /api/debug/inject_utterance` 대체 |
| Gemma 4 LLM | `LLM_SERVICE_URL` | `POST /infer` | 수동 버튼이 엔드포인트 직접 호출 시 미사용 |
| Dice/Horse Robot | `ROBOT_SERVICE_URL` | `POST /dice/roll`, `POST /horse/move`, `POST /base_position` | `/api/dice/request`, Step 5 물리 실행, Step 2 |

- 각 어댑터는 **선택적**(optional) — 환경변수 미설정 시 no-op/스텁 모드. 기동 배너에 모드 상태를 로깅.

### 7.3 Money
(§3.4 참고)

### 7.4 Property
(§4.4 참고)

### 7.5 Effects (chance/community chest)
| POST | `/api/effects/move_to_tile` |
| POST | `/api/effects/collect` |
| POST | `/api/effects/pay` |
| POST | `/api/effects/go_to_jail` |

### 7.6 Robot (proxy to Dice/Horse Pick-and-Place FastAPI)
| POST | `/api/robot/base_position` | 외부 `ROBOT_SERVICE_URL/base_position` 프록시, 실패 허용 |
| POST | `/api/robot/roll_dice` | 외부 `ROBOT_SERVICE_URL/dice/roll` 프록시, 응답 값 `/api/dice/submit` 연결 |
| POST | `/api/robot/move_piece` | `{from_tile, to_tile}` → 외부 `/horse/move`, fire-and-forget |
| GET  | `/api/robot/health` | 어댑터가 연결 가능한지 확인 (UI 배지용) |

> **주의:** 본 패키지는 `movensys_vlm`의 MoveIt2 서비스를 **더 이상 직접 호출하지 않는다**. 물리 실행은 전적으로 외부 Dice/Horse pick-and-place FastAPI 서비스가 담당한다.

### 7.7 Debug / Manual mode (AI·로봇 없이 전체 플레이)
| POST | `/api/debug/inject_utterance` | Whisper 미기동 시 텍스트 발화 직접 주입 |
| POST | `/api/debug/simulate_llm_intent` | Gemma 미기동 시 의도(`intent`, `args`)를 직접 주입 |
| POST | `/api/debug/force_dice` | 주사위 값 강제 지정 (개발용) |
| POST | `/api/debug/force_state` | 테스트 시나리오 재현용 상태 덮어쓰기 |

### 7.7 Cameras (movensys_vlm 이식)
| WS | `/api/stream/image_top/{rgb,depth,camera_info}` |
| WS | `/api/stream/image_hand/{rgb,depth,camera_info}` |

### 7.8 Board assets
| GET | `/api/board/definition?id={1,2,3}` — 타일 레이아웃 JSON |
| GET | `/api/board/snapshot` — Step 10용 (이미지+힌트) |

---

## 8. 외부 의존성 (구현 범위 밖)

본 패키지가 **받아 쓰는** FastAPI 서비스는 아래 **3개 + 선택 1개**뿐이다.

| # | 의존 | 인터페이스 | 환경변수 | 부재 시 대체 전략 |
|---|---|---|---|---|
| 1 | Whisper AI (FastAPI) | `POST /stt` `{audio}` → `{text}` | `STT_SERVICE_URL` | `POST /api/debug/inject_utterance` — UI 텍스트 입력창 |
| 2 | Gemma 4 (FastAPI) | `POST /infer` `{text\|image_b64, context}` → `{intent, args}` | `LLM_SERVICE_URL` | `POST /api/debug/simulate_llm_intent` — UI 수동 버튼이 의도별 엔드포인트 직접 호출 |
| 3 | Dice & Horse Pick-and-Place (FastAPI) | `POST /dice/roll` → `{value}`, `POST /horse/move` `{player_id, from_tile, to_tile}`, `POST /base_position` | `ROBOT_SERVICE_URL` | `dice_source = "rng"` 또는 `"manual"`, 말 이동은 화면 애니메이션만 |
| 4 | Isaac Sim (선택) | ROS 2 bridge, chance 카드 소환 토픽 | — | 완전 선택 — 데모 용 |

### 8.1 부재 시 동작 보증

어느 외부 서비스가 없더라도 **Board 1/2/3의 모든 규칙은 완전 동작한다.**
- 환경변수가 비어있으면 어댑터는 기동 시 "stub mode" 로그만 남기고 no-op 처리
- UI 상단에 "AI: off / Robot: off" 배지가 표시되고, 수동 컨트롤 패널이 항상 활성화
- 자동 테스트는 모든 외부 서비스를 환경변수 없이 기동한 상태에서 통과해야 한다 (§9)

---

## 9. 테스트 전략

**원칙:** 모든 테스트는 **외부 FastAPI 3종이 기동되지 않은 상태**에서 통과해야 한다.

1. **Board 3 smoke test (headless)**: 주사위 submit → 말 이동 → 한 바퀴 → winner 확인 — AI/로봇 없이
2. **Board 1 rules unit test**: `pytest tests/board1/` — 매입/건설/임대/파산
3. **Board 2 rules unit test (`pytest tests/board2/`)** — 감옥 FSM, 역 임대료, 유틸리티 임대료, 세금, 색상그룹 독점 임대료 배수, 균등 건설, 커뮤니티체스트 덱, 저당/해제, 시작점 보너스
4. **Adapter stub test**: 환경변수 미설정 상태에서 어댑터가 `stub mode`로 기동되고 모든 수동 엔드포인트가 정상 작동하는지 확인
5. **UI 시각 검증**: Playwright 또는 수동 — 돈 감소 모션, 건물 누적, property 썸네일, "AI: off / Robot: off" 배지
6. **Adapter integration test (선택)**: 외부 FastAPI 3종 기동 시 end-to-end 경로 검증 — 단, CI에서는 건너뛴다

---

## 10. 오픈 이슈 / 컨펌 필요

1. **Property/Chance 카드 아트** — §2.4의 3가지 옵션 중 선택. 추천: **(2) 자체 제작 단순 SVG**로 시작 후, 여유 되면 (1) 오픈소스 에셋 교체.
2. **10-4 Board 1/2 확장 규칙** — §10-4의 제안안 수락/수정. (Board 2는 §10-4-B에서 이미 전부 자체 구현 가능하다고 정의됨)
3. **플레이어 색상** — user=빨강, robot=파랑 가정. 변경 시 `/api/game/config` 에 색상 설정 노출 필요.
4. **파산 처리** — 자동 매각 순서(건물 → 저당 → 원본 property) 확정.
5. **외부 FastAPI 3종 스펙 확정** — Whisper·Gemma·Dice/Horse 각 팀과 `POST` 바디/응답 스키마 합의 (§0.2, §8).
6. **외부 FastAPI 엔드포인트 보안** — 본 패키지의 `/api/...`를 외부 서비스에 어떻게 노출할지 (로컬 네트워크 한정 권장).

---

## 11. 마일스톤 (제안)

**재설계 원칙:** Board 2 풀 규칙을 **외부 의존성보다 먼저** 완성한다. 외부 FastAPI 3종은 순차 통합 단계에서 각각의 어댑터에 연결된다.

| 단계 | 범위 | 산출물 | 외부 FastAPI 필요? | CI 활성화 |
|---|---|---|---|---|
| M0 | 디렉토리/Docker/FastAPI skeleton + **CI 워크플로 신규 추가** | `docker compose up` → `/api/health` OK, CI가 syntax + health check 통과 | 없음 | ✅ syntax, health, stub mode |
| M1 | Board 3 headless E2E | 수동 주사위 입력만으로 한 바퀴 → winner | 없음 | ✅ Board 3 smoke E2E 추가 |
| M2 | Board 1 property/돈/건물/임대료 + Chance | 수동 UI로 규칙 전수 검증 | 없음 | ✅ Board 1 rules suite 추가 |
| **M3** | **Board 2 풀 규칙 (§10-4-B 전부)** | **감옥·역·유틸리티·세금·색상그룹 독점·커뮤니티체스트·저당 — pytest 전수 통과** | **없음** | ✅ Board 2 rules suite 추가 |
| M4 | 카메라 스트림 이식 | `cameras.html` 작동 (이미지 표시만) | 없음 (ROS 2 카메라 토픽만) | ✅ ROS 2 이미지 로직 syntax |
| M5 | Adapter #3 통합: Dice/Horse Pick-and-Place FastAPI | 로봇 서비스 기동 시 주사위/말 이동이 실제 로봇으로 라우팅 | 3번 (Robot) | CI엔 stub mode 경로만 |
| M6 | Adapter #1 통합: Whisper FastAPI | 음성 입력 → 텍스트 경로 동작 | 1번 (STT) | CI엔 stub mode 경로만 |
| M7 | Adapter #2 통합: Gemma 4 FastAPI | 텍스트·보드 이미지 → 의도 → 엔드포인트 호출 | 2번 (LLM) | CI엔 stub mode 경로만 |
| M8 | (선택) Chance 카드 아트 + Isaac Sim 연동 | 카드 이미지 정제, Isaac 카드 소환 | Isaac (선택) | — |

각 M5~M7은 독립적으로 진행 가능하며, 어떤 순서로든 통합할 수 있다. 통합되지 않은 항목은 수동 모드가 계속 책임진다.

---

## 12. CI/CD — "최소 기능 자동 검증"

### 12.1 원칙

- **외부 FastAPI 3종(Whisper·Gemma·Dice/Horse)을 전혀 기동하지 않은 상태**에서 통과하는 검사만 CI에 넣는다.
- CI는 **마일스톤과 함께 점진적으로 확장**된다. 해당 산출물이 아직 없는 단계에서는 그 스텝을 "SKIP"으로 처리하고 FAIL하지 않는다 (단, 해당 산출물의 마일스톤이 끝난 이후에는 SKIP 자체가 실패 신호가 됨 — §12.4 참조).
- 로봇/카메라를 위한 ROS 2 설치는 `movensys_vlm` CI와 동일하게 `ros-tooling/setup-ros`로 제공한다. 단, **게임 엔진 테스트는 ROS 2 없이도 순수 Python만으로 돌 수 있어야** 한다 (`game/*` 모듈은 ROS 2 의존 금지).

### 12.2 CI 파이프라인 단계

파일: `.github/workflows/movensys-monopoly.yml`
트리거: `movensys-monopoly/**` 경로의 PR (branch: `main`, `devel`)
매트릭스 (초기): `{ros_distro: jazzy, os: ubuntu-24.04}` — 추후 `humble + ubuntu-22.04` 추가 가능.

| # | 스텝 | 검증 대상 | 활성 마일스톤 |
|---|---|---|---|
| 1 | Checkout & Python/ROS 설치 | 환경 준비 | 상시 |
| 2 | 의존성 설치 (`movensys-monopoly/requirements.txt`) | 패키지 해결 가능성 | M0+ |
| 3 | **Python 문법 체크** (`py_compile` 모든 `.py`) | import·괄호 등 구조 깨짐 없음 | M0+ |
| 4 | **Game engine 단위 테스트** (`pytest movensys-monopoly/tests/game/`) | 보드 규칙 순수 로직 | M1+ (Board 3부터) |
| 5 | **FastAPI 헬스 체크** (uvicorn 기동 → `curl /api/health`) | 앱이 뜨고 기본 라우트 응답 | M0+ |
| 6 | **Board 3 headless E2E** (`pytest movensys-monopoly/tests/e2e/test_board3_smoke.py`) | 주사위 submit → 이동 → winner 판정 | M1+ |
| 7 | **Board 1 rules suite** (`pytest movensys-monopoly/tests/board1/`) | 매입·건설·임대·파산 | M2+ |
| 8 | **Board 2 rules suite** (`pytest movensys-monopoly/tests/board2/`) | 감옥·역·유틸리티·세금·독점·커뮤니티체스트·저당 | M3+ |
| 9 | **Adapter stub mode test** (`STT_SERVICE_URL`/`LLM_SERVICE_URL`/`ROBOT_SERVICE_URL` 전부 미설정 상태에서 §12.2-5~8 전부 통과) | "외부 서비스 없이도 완전 동작" 불변 | M0+ |

### 12.3 "최소 기능 검증" 스모크 테스트 정의 (M0~M1)

아래는 CI가 반드시 통과시켜야 하는 **최소 기능 집합**이다. M1 완료 시점에 전부 활성화되어야 한다.

1. **앱이 뜬다**: `uvicorn main:app` 10초 내 `/api/health` → 200 OK, body `{"status": "ok"}`
2. **Board 3 시작 가능**: `POST /api/game/start {board: "3"}` → 200, `GameState.fsm == "TURN_START"`
3. **주사위 수동 제출**: `POST /api/dice/submit {value: 3, source: "manual"}` → 200
4. **말 이동 적용**: `POST /api/move/apply {player_id, from_tile: 0, to_tile: 3}` → 200, `GameState.positions[player_id] == 3`
5. **검증 불일치 시 409**: `to_tile`이 계산과 다르면 409 Conflict
6. **승리 판정**: 한 바퀴 돌고 나면 `GET /api/game/winner` → `{winner: "user" | "robot"}`
7. **스텁 모드 배너**: 환경변수 미설정 시 `/api/robot/health` → `{mode: "stub"}`, 로그에 `AI: off / Robot: off`

이 7개가 통과하면 **AI/로봇 없이도 모노폴리의 핵심 루프가 작동함**을 보장한다.

### 12.4 Milestone gating (SKIP → FAIL 전이)

각 테스트 suite는 해당 마일스톤 완료 후 **존재하지 않으면 실패**하도록 전환한다. 기본 스크립트 패턴:

```bash
REQUIRE_FROM_MILESTONE="M3"
CURRENT_MILESTONE="${MONOPOLY_MILESTONE:-M0}"
if ! [ -d movensys-monopoly/tests/board2 ]; then
  if [ "$CURRENT_MILESTONE" \> "$REQUIRE_FROM_MILESTONE" ] || [ "$CURRENT_MILESTONE" = "$REQUIRE_FROM_MILESTONE" ]; then
    echo "FAIL: tests/board2/ must exist from $REQUIRE_FROM_MILESTONE"
    exit 1
  fi
  echo "SKIP: tests/board2/ not expected until $REQUIRE_FROM_MILESTONE"
fi
```

`MONOPOLY_MILESTONE`은 워크플로 env에서 주입 (M0~M8). 각 PR이 어느 마일스톤을 초과하는지 컨트롤할 수 있다.

### 12.5 CI에 **넣지 않는** 것

- 외부 FastAPI 3종 실제 호출 (Whisper/Gemma/로봇) — CI 환경에는 존재하지 않는다.
- Docker Compose 통합 빌드 — 시간이 오래 걸리고, 현재 리포의 CI 정책은 "GitHub CI에서 docker를 쓰지 않음" (커밋 `cb4f1f6` 기준).
- Isaac Sim 연동 — 별도 환경 필요, 로컬/전용 러너로 이관.
- UI 시각 회귀 (Playwright) — 별도 워크플로로 분리 예정 (§9 4번).
- ROS 2 실제 토픽 통신 — 로컬/리그러너에서만 실행.

### 12.6 로컬 재현

CI와 동일한 검사를 개발자가 로컬에서 바로 돌릴 수 있게 `movensys-monopoly/scripts/ci_local.sh` 제공:

```bash
cd movensys-monopoly
./scripts/ci_local.sh   # §12.2 2~9번 순서 그대로 실행
```

이 스크립트는 GitHub Actions YAML의 "스텝 명령줄"과 1:1로 동일해야 한다 (드리프트 방지).
