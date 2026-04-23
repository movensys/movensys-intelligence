#!/usr/bin/env bash
# Local reproduction of .github/workflows/movensys-monopoly.yml.
# Keep in 1:1 lockstep with the workflow YAML (see PRD.md §14).
#
# External FastAPI URLs are intentionally empty — proves stub-mode invariant.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

export STT_SERVICE_URL=''
export LLM_SERVICE_URL=''
export ROBOT_SERVICE_URL=''

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31mFAIL:\033[0m %s\n' "$*"; exit 1; }

step "Install Python dependencies"
[ -f requirements.txt ] && pip3 install --no-cache-dir -r requirements.txt
pip3 install --no-cache-dir pytest pytest-asyncio httpx uvicorn fastapi

step "Python syntax check"
mapfile -t files < <(find . -type f -name '*.py' \
  -not -path './.venv/*' -not -path './build/*' -not -path './__pycache__/*')
for f in "${files[@]}"; do
  echo "  $f"; python3 -m py_compile "$f"
done

step "FastAPI health + stub-mode invariant"
if [ -f main.py ]; then
  python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 &
  pid=$!
  trap 'kill $pid 2>/dev/null || true' EXIT
  for _ in $(seq 1 20); do
    curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
    sleep 1
  done
  body=$(curl -sf http://127.0.0.1:8000/api/health) || fail "/api/health did not respond"
  echo "  health: $body"
  echo "$body" | grep -q '"status"' || fail "health missing status"

  robot=$(curl -sf http://127.0.0.1:8000/api/robot/health) || fail "/api/robot/health did not respond"
  echo "  robot: $robot"
  echo "$robot" | grep -Eq '"mode"[[:space:]]*:[[:space:]]*"stub"' \
    || fail "adapter not in stub mode with empty ROBOT_SERVICE_URL"

  kill $pid 2>/dev/null || true
  trap - EXIT
else
  echo "  main.py not present — skipped"
fi

step "Pytest"
if [ -d tests ]; then
  rc=0
  python3 -m pytest -v tests/ || rc=$?
  # Exit code 5 = "no tests collected" — acceptable at early milestones.
  if [ "$rc" != "0" ] && [ "$rc" != "5" ]; then exit "$rc"; fi
else
  echo "  tests/ not present — nothing to run"
fi

printf '\n\033[1;32m==> ci_local passed\033[0m\n'
