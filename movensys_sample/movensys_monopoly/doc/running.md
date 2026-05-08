# Running movensys-monopoly

명령 참조. 자세한 스펙은 [`PRD.md`](./PRD.md).

모든 경로는 `movensys-monopoly/` 기준.

---

## 1. 로컬 개발 (uvicorn)

### 실행

```bash
cd movensys-monopoly
python3 -m uvicorn main:app --host 0.0.0.0 --port 7999
```

브라우저: <http://localhost:7999>

백그라운드 실행:

```bash
python3 -m uvicorn main:app --host 0.0.0.0 --port 7999 >/tmp/monopoly.log 2>&1 &
```

### 종료

```bash
pkill -f 'uvicorn main:app'
```

확인:

```bash
pgrep -fa 'uvicorn main:app' || echo "no uvicorn running"
```

---

## 2. Docker Compose

### 실행

```bash
cd movensys-monopoly/docker
docker compose down
docker compose up -d --build
docker compose up
```

### 로그

```bash
docker compose logs -f monopoly
```

### 종료

```bash
docker compose down                # 컨테이너 제거
docker compose stop                # 중지만(다음에 `up` 으로 재개)
```

---

## 3. 테스트

### 단위 + E2E 전수

```bash
cd movensys-monopoly
python3 -m pytest tests/ -v
```

### 특정 suite만

```bash
python3 -m pytest tests/game/ -v              # 게임 엔진 단위
python3 -m pytest tests/e2e/ -v               # FastAPI E2E
python3 -m pytest tests/game/test_rules_board3.py::test_full_lap_board3_wins_on_wrap -v
```

### 로컬 CI 재현 (GitHub Actions와 동일 스텝)

```bash
cd movensys-monopoly
./scripts/ci_local.sh
```

---

## 4. 환경 변수 (선택)

전부 비우면 stub 모드로 기동 (기본값). PRD §10.1 참조.

```bash
# 외부 FastAPI 어댑터 (live 모드로 전환)
export STT_SERVICE_URL=http://whisper:8001
export LLM_SERVICE_URL=http://gemma:8002
export ROBOT_SERVICE_URL=http://robot:8003

# 서버 옵션
export MONOPOLY_PORT=7999
export MONOPOLY_LOG_LEVEL=INFO
export MONOPOLY_DEBUG_ROUTES=true         # false 시 /api/debug/* 404

# ROS 2
export ROS_DOMAIN_ID=0
export MONOPOLY_ISAAC_TOPIC_CARD_SPAWN=/isaac/card_spawn

python3 -m uvicorn main:app --port 7999
```

---

## 5. 헬스 체크 / 상태 조회

```bash
curl -s http://localhost:7999/api/health
curl -s http://localhost:7999/api/robot/health          # stub|live
curl -s http://localhost:7999/api/game/state | python3 -m json.tool
curl -s http://localhost:7999/api/game/winner
```

WebSocket 이벤트 구독 (예: websocat 사용):

```bash
websocat ws://localhost:7999/api/stream/game
```

---

## 6. 게임 한 판 (CLI 예시)

```bash
API=http://localhost:7999/api

curl -s -X POST $API/game/start     -H 'Content-Type: application/json' -d '{"board":"3"}'
curl -s -X POST $API/dice/submit    -H 'Content-Type: application/json' -d '{"value":3,"source":"manual"}'
curl -s -X POST $API/move/apply     -H 'Content-Type: application/json' -d '{"player":"user","from_tile":0,"to_tile":3}'
curl -s -X POST $API/game/end_turn
```

---

## 7. 자주 걸리는 것

| 증상 | 원인 / 해결 |
|---|---|
| `ERROR: Error loading ASGI app. Could not import module "main"` | `movensys-monopoly/`로 `cd` 안 함. 실행 디렉토리 확인. |
| `externally-managed-environment` (pip install) | Ubuntu 24.04 PEP 668. `pip3 install --break-system-packages ...` 또는 `python3 -m venv .venv && source .venv/bin/activate` |
| `Address already in use` (port 7999) | 이전 프로세스 살아있음. `pkill -f 'uvicorn main:app'` 또는 `MONOPOLY_PORT=8001` 로 다른 포트 사용. |
| UI 배지에 `ROS2:on` 표시 | 로컬에 ROS 2가 설치돼 있어 `rclpy.init()` 성공. M0 시점에 카메라·Isaac 토픽은 아직 없음(§M4). 정상. |
