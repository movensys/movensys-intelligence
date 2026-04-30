# PRD (쉽게 읽는 버전) — movensys-monopoly

비개발자를 위한 1페이지 요약. **v0.3 (2026-04-24)**
기술 상세는 [`PRD.md`](./PRD.md). 이 문서는 원문을 **복붙하지 않는다** — 결정 맥락과 용어집만 제공.

---

## 한 줄 요약

사람 1명과 로봇팔 1대가 실물 모노폴리 보드로 같이 놀 수 있게 해주는 단일 FastAPI 웹 서비스.

---

## 가장 중요한 한 가지

> **AI도 로봇도 없이 보드 1/2/3 전부가 완전히 돌아간다.**

이것이 설계의 중심 원칙이다. 다른 팀이 FastAPI를 늦게 주더라도 우리는 막히지 않는다.
자세한 이유와 구조는 PRD.md §3 (Architecture).

---

## 그림 하나

```
[사람] → [Whisper] → [Gemma 4] ──┐
                                   │ REST
                                   ▼
                          [movensys-monopoly]  ←── (우리가 만드는 것)
                                   │
                                   ▼
                        [주사위·말 로봇 FastAPI]
```

- 왼쪽 2개와 맨 아래 1개, **총 3개의 FastAPI가 외부에서 받아오는 것**.
- 가운데가 우리 책임. 받아야 할 FastAPI가 없으면 **수동 버튼**이 같은 일을 한다.

---

## 받아오는 3개 (전부 없어도 게임 돌아감)

| # | FastAPI | 역할 | 없을 때 |
|---|---|---|---|
| 1 | Whisper AI | 음성 → 글자 | 텍스트 입력창 |
| 2 | Gemma 4 | 글자·사진 → 게임 의도 | UI 버튼 직접 호출 |
| 3 | 주사위·말 pick-and-place | 실제 로봇 동작 | 화면 애니메이션만 |

상세 인터페이스: PRD.md §8.

---

## 보드 3종

| 보드 | 용도 | 규칙 복잡도 | 외부 FastAPI 필요? |
|---|---|---|---|
| Board 3 | 파이프라인 스모크 테스트 | 없음 (12칸 빈판, 한 바퀴 승리) | 아니오 |
| Board 1 | 단축 시연용 | 중간 (돈·건물·chance) | 아니오 |
| Board 2 | 원본 40칸 풀 규칙 | 최상 (감옥·역·유틸리티·세금·독점·CC·저당) | **아니오 — 순수 계산 로직** |

각 보드의 정확한 규칙: PRD.md §7.
Board 3의 타일 번호는 **좌상단 START → 시계방향으로 0,1,2…11** 로 매겨진다(v0.3에서 확정, PRD §7.1).

---

## 일정 (v0.3에서 재편)

| 단계 | 언제 | 외부 FastAPI | 상태 |
|---|---|---|---|
| M0 | 스켈레톤 + Docker + CI | 필요 없음 | ✅ |
| M1 | Board 3 E2E 스모크 | 필요 없음 | ✅ |
| M2 | Board 1 풀 규칙 | 필요 없음 | ✅ |
| **M3** | **카메라 WS 프록시 + Isaac 카드 소환 토픽** | 필요 없음 | ✅ |
| M4 | 주사위·말 로봇 어댑터 연결 | 로봇 FastAPI | |
| M5 | Whisper STT 연결 | Whisper | |
| M6 | Gemma 4 LLM 연결 | Gemma | |
| M7 | (선택) Chance 카드 아트 + Isaac 스펙 확정 | Isaac | |
| (보류) | Board 2 풀 규칙 | 필요 없음 | M3 이후 |

각 단계의 구체적 완료 기준: PRD.md §15.
**변경 이유**: v0.3에서 Board 2 작업을 일시 보류하고 카메라/Isaac을 먼저 끌어올림. 시뮬레이션·실물 시연 준비가 규칙 엔진 완성도보다 앞선 병목이었음.

---

## 품질 보증은 CI가 한다

PR 올릴 때마다 GitHub Actions가 자동으로 검증:

1. Python 문법 체크
2. 앱이 뜨고 `/api/health` 응답
3. 외부 FastAPI URL이 **비어있는 상태**에서 `/api/robot/health`가 `{"mode":"stub"}` 리턴
4. `tests/` 안의 모든 pytest 통과 (Board 3/1/2 시나리오, 규칙 엔진)

CI가 녹색 = **외부 의존성 하나도 없이도 게임이 동작함**을 기계적으로 증명.

로컬 동일 재현: `movensys-monopoly/scripts/ci_local.sh`
상세 파이프라인: PRD.md §14.

---

## 실행 방법

```bash
cd ~/workspaces/.../movensys-monopoly
./docker/run.sh             # 빌드 + 실행 + 헬스 대기 + 상태 요약 (권장)
# 브라우저: http://localhost:8000   (카메라 전체 뷰: /cameras)
./docker/stop.sh            # 종료 + 포트·ROS 노드 잔여 검증
```

`run.sh`는 시작 전에 **8000 포트 점유**와 **중복 ROS 노드**를 먼저 체크해 고스트 인스턴스 위에 덧붙지 않도록 막는다(v0.3 신설, PRD §14).

외부 FastAPI 연결이 있을 때만 설정:
```bash
export STT_SERVICE_URL=http://whisper:8001
export LLM_SERVICE_URL=http://gemma:8002
export ROBOT_SERVICE_URL=http://robot:8003
```

---

## 용어 빠르게

| 용어 | 뜻 |
|---|---|
| Headless | AI·로봇 없이 서버만으로 게임 진행 |
| Stub mode | 외부 FastAPI URL이 비어 있을 때의 동작 (no-op / RNG) |
| Adapter | 외부 FastAPI를 얇게 감싼 HTTP 클라이언트 (`adapters/*.py`) |
| Fire-and-forget | 로봇에게 명령만 쏘고 응답 안 기다림 |
| FSM | 유한 상태 기계 — 턴이 어느 단계인지 추적 |
| Monopoly bonus | 같은 색 그룹 독점 시 임대료 2배 + 건물 건설 가능 (Board 2) |
| Camera dock | 뷰포트 우하단에 고정된 카메라 썸네일 오버레이 (v0.3) |
| Reset (버튼) | 현재 보드를 1턴부터 다시 시작. Start는 드롭다운 선택, Reset은 현 보드 유지 (v0.3) |
| Isaac card-spawn | Chance/CC 카드 뽑을 때 Isaac Sim에 카드 소환을 알리는 ROS 토픽 publish |

---

## 개발 체크리스트

PR 단위로 쪼갠 실행 목록은 **PRD.md §16 Development Checklist**. M0~M8 각각에 들어갈 구체적 작업 항목 + 교차 관심사(영속성·메트릭·README).

---

## 확정 안 된 것 (컨펌 대기)

PRD.md §17 Open Questions. 외부 FastAPI 스펙, 플레이어 색상 기본값, Isaac 토픽 페이로드 등.

---

## v0.3에서 달라진 것 (2026-04-24)

한눈에 보는 주요 변경 — 상세는 PRD.md §1.2.

- **M3 교체**: Board 2 규칙(보류) → **카메라 스트림 + Isaac 카드 소환 토픽** ✅
- **Start/Reset 분리**: Start는 새 보드 선택, Reset은 현 보드 유지 재시작. 서버는 언제 눌러도 리셋
- **모드 배지 폴링 제거**: 4개 `/health` 엔드포인트를 5초마다 긁던 코드를 `/api/modes` 1회 호출로 대체
- **UI 정비**: Board 3 START 좌상단·시계방향, 말 아이콘 사각형, 카메라 도크 고정 오버레이
- **Docker 안전장치**: `docker/run.sh`/`stop.sh` 런처가 포트·ROS 노드 사전 점검 + compose 프로젝트 격리
