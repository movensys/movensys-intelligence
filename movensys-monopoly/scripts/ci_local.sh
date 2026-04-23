#!/usr/bin/env bash
# Local reproduction of the GitHub Actions workflow at
# .github/workflows/movensys-monopoly.yml.
#
# Run from the movensys-monopoly/ directory (or anywhere — it cd's itself).
# Keep this script in 1:1 lockstep with the workflow YAML to avoid drift
# (see doc/PRD.md §12.6).
#
# Required external services: NONE. All adapter URLs are intentionally left
# empty so the game engine is exercised in stub mode (§0.1, §8.1).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

: "${MONOPOLY_MILESTONE:=M0}"
export STT_SERVICE_URL=''
export LLM_SERVICE_URL=''
export ROBOT_SERVICE_URL=''

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
skip() { printf '\033[1;33mSKIP:\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mFAIL:\033[0m %s\n' "$*"; exit 1; }

# ---------- 2. Install deps ----------
step "Install Python dependencies"
if [ -f requirements.txt ]; then
  pip3 install --no-cache-dir -r requirements.txt
else
  skip "requirements.txt not present yet"
fi
pip3 install --no-cache-dir pytest httpx uvicorn fastapi

# ---------- 3. Syntax check ----------
step "Python syntax check (py_compile)"
mapfile -t files < <(find . -type f -name '*.py' \
  -not -path './.venv/*' -not -path './build/*' -not -path './__pycache__/*')
if [ "${#files[@]}" -eq 0 ]; then
  [ "$MONOPOLY_MILESTONE" = "M0" ] && skip "no .py files yet" \
    || fail "no .py files but milestone is $MONOPOLY_MILESTONE"
else
  for f in "${files[@]}"; do
    echo "  $f"; python3 -m py_compile "$f"
  done
fi

# ---------- 5. Health check ----------
step "FastAPI health smoke test"
if [ ! -f main.py ]; then
  [ "$MONOPOLY_MILESTONE" = "M0" ] && skip "main.py not yet present" \
    || fail "main.py must exist from M0 onward"
else
  python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 &
  pid=$!
  trap 'kill $pid 2>/dev/null || true' EXIT
  for _ in $(seq 1 20); do
    curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
    sleep 1
  done
  body=$(curl -sf http://127.0.0.1:8000/api/health) || fail "/api/health did not respond"
  echo "  $body"
  echo "$body" | grep -q '"status"' || fail "health response missing status field"
  kill $pid 2>/dev/null || true
  trap - EXIT
fi

# ---------- 6. Adapter stub mode ----------
step "Adapter stub mode check"
if [ -f main.py ]; then
  python3 -m uvicorn main:app --host 127.0.0.1 --port 8001 &
  pid=$!
  trap 'kill $pid 2>/dev/null || true' EXIT
  for _ in $(seq 1 20); do
    curl -sf http://127.0.0.1:8001/api/health >/dev/null 2>&1 && break
    sleep 1
  done
  if curl -sf http://127.0.0.1:8001/api/robot/health >/dev/null 2>&1; then
    robot_health=$(curl -sf http://127.0.0.1:8001/api/robot/health)
    echo "  $robot_health"
    echo "$robot_health" | grep -q '"mode"[[:space:]]*:[[:space:]]*"stub"' \
      || fail "adapter did not report stub mode with empty ROBOT_SERVICE_URL"
  else
    [ "$MONOPOLY_MILESTONE" = "M0" ] && skip "/api/robot/health not yet present" \
      || fail "/api/robot/health missing past M0"
  fi
  kill $pid 2>/dev/null || true
  trap - EXIT
fi

# ---------- 7. Game engine tests ----------
step "Game engine unit tests"
if [ -d tests/game ]; then
  python3 -m pytest -v tests/game/
else
  [ "$MONOPOLY_MILESTONE" = "M0" ] && skip "tests/game/ expected from M1" \
    || fail "tests/game/ must exist from M1 onward"
fi

# ---------- 8. Board 3 E2E ----------
step "Board 3 headless E2E"
if [ -f tests/e2e/test_board3_smoke.py ]; then
  python3 -m pytest -v tests/e2e/test_board3_smoke.py
else
  [ "$MONOPOLY_MILESTONE" = "M0" ] && skip "Board 3 E2E expected from M1" \
    || fail "tests/e2e/test_board3_smoke.py must exist from M1 onward"
fi

# ---------- 9. Board 1 rules ----------
step "Board 1 rules suite"
if [ -d tests/board1 ]; then
  python3 -m pytest -v tests/board1/
else
  case "$MONOPOLY_MILESTONE" in
    M0|M1) skip "tests/board1/ expected from M2" ;;
    *)     fail "tests/board1/ must exist from M2 onward" ;;
  esac
fi

# ---------- 10. Board 2 rules ----------
step "Board 2 rules suite"
if [ -d tests/board2 ]; then
  python3 -m pytest -v tests/board2/
else
  case "$MONOPOLY_MILESTONE" in
    M0|M1|M2) skip "tests/board2/ expected from M3" ;;
    *)        fail "tests/board2/ must exist from M3 onward" ;;
  esac
fi

printf '\n\033[1;32m==> CI-local passed (milestone: %s)\033[0m\n' "$MONOPOLY_MILESTONE"
