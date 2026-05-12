#!/usr/bin/env bash
# Tear down movensys-monopoly and verify nothing was left dangling:
#   - compose down --remove-orphans removes every service container
#   - confirm port :${MONOPOLY_PORT:-7999} is released (catches a rogue
#     host-level uvicorn still holding the port)
#   - confirm no /movensys_monopoly node remains in the DDS graph (after
#     a short grace period for the announcement TTL)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${MONOPOLY_PORT:-7999}"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }

step "compose down --remove-orphans"
docker compose -f "$HERE/docker-compose.yml" down --remove-orphans

step "Post-flight: port :$PORT"
if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
  owner=$(ss -ltnp "sport = :$PORT" 2>/dev/null | tail -n +2 | head -1 || true)
  warn "port :$PORT is still held after compose down: $owner"
else
  echo "  released"
fi

step "Post-flight: ROS 2 graph"
if command -v ros2 >/dev/null 2>&1; then
  # DDS node announcements can linger briefly after shutdown; give them a
  # grace window before flagging.
  sleep 2
  count=$(ros2 node list 2>/dev/null | grep -c '^/movensys_monopoly$' || true)
  if [ "${count:-0}" -gt 0 ]; then
    warn "$count /movensys_monopoly node(s) still visible in the DDS graph"
  else
    echo "  no stray nodes"
  fi
else
  echo "  ros2 CLI not in PATH — skipped"
fi
