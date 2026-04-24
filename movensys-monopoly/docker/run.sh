#!/usr/bin/env bash
# Launch movensys-monopoly via docker compose with the same safeguards
# as scripts/ci_local.sh:
#   - Refuse to start if host port ${MONOPOLY_PORT:-8000} is held by
#     something that is NOT our own container (prevents silent shadowing
#     by a stray uvicorn on the host).
#   - Warn if a stray /movensys_monopoly node is already in the ROS 2
#     graph (duplicate nodes poison /image_*/DDS subscriptions).
#   - Bring the stack up with --remove-orphans so old service containers
#     from prior compose runs get swept.
#   - Wait on the Docker healthcheck and surface a clear error on
#     "unhealthy" instead of a blank prompt.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${MONOPOLY_PORT:-8000}"
CONTAINER="movensys_monopoly_container"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31mFAIL:\033[0m %s\n' "$*"; exit 1; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }

step "Pre-flight: port :$PORT"
if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
  if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "  port held by our container — compose will recreate"
  else
    fail "port :$PORT held by a non-container process (uvicorn/other). Stop it, then retry."
  fi
fi

step "Pre-flight: ROS 2 graph"
if command -v ros2 >/dev/null 2>&1; then
  if ros2 node list 2>/dev/null | grep -c '^/movensys_monopoly$' | grep -qv '^0$'; then
    count=$(ros2 node list 2>/dev/null | grep -c '^/movensys_monopoly$' || true)
    if [ "${count:-0}" -gt 0 ]; then
      if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
        echo "  $count /movensys_monopoly node(s) visible — expected from the running container"
      else
        warn "$count stray /movensys_monopoly node(s) in the DDS graph with no container running. They'll be replaced on startup but duplicate nodes can delay subscription binding."
      fi
    fi
  fi
else
  echo "  ros2 CLI not in PATH — skipping graph check"
fi

step "compose up -d --remove-orphans"
docker compose -f "$HERE/docker-compose.yml" up -d --remove-orphans

step "Waiting for healthcheck"
deadline=$((SECONDS + 60))
while :; do
  status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo "unknown")
  case "$status" in
    healthy)   echo "  healthy"; break ;;
    unhealthy) fail "container is unhealthy — last log lines:\n$(docker logs --tail 30 $CONTAINER 2>&1)" ;;
    starting|unknown)
      [ $SECONDS -ge $deadline ] && fail "healthcheck did not pass within 60s"
      sleep 2 ;;
    *) fail "unexpected health status: $status" ;;
  esac
done

step "Summary"
# Make it unambiguous that the container keeps running detached after
# this script exits — the prompt returning is not the container dying.
docker ps --filter name="$CONTAINER" --format '  {{.Names}}  {{.Status}}'
echo
echo "  UI    : http://127.0.0.1:$PORT/   cameras: http://127.0.0.1:$PORT/cameras"
echo "  logs  : docker logs -f $CONTAINER"
echo "  stop  : $HERE/stop.sh"
