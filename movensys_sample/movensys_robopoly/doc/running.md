# Running movensys-monopoly

## 1. Local development (uvicorn)

Use a virtual environment so the project's pinned versions don't fight
with system Python packages:

```bash
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
python3 -m uvicorn main:app --host 0.0.0.0 --port 7999
```

### Stop

```bash
pkill -f 'uvicorn main:app'
```

Verify nothing is left:

```bash
pgrep -fa 'uvicorn main:app' || echo "no uvicorn running"
```

---

## 2. Docker Compose

### Run

```bash
cd docker
docker compose down
docker compose up -d --build
```

### Logs

```bash
docker compose logs -f
```

---

## 3. Dry-run mode (no hardware)

When `MOVENSYS_PNP_DRY_RUN` is truthy,
[`pick_and_place.py`](../pick_and_place.py) short-circuits every
interaction with the manipulator stack:

- Testing the monopoly server flow on a workstation with no robot attached.
- Iterating on game logic / UI without burning robot cycles between attempts.
- CI / integration tests that exercise the rules engine and FastAPI surface end-to-end.

### How to enable

The flag is **off by default** — the compose file exposes it as a pass-through env var (`MOVENSYS_PNP_DRY_RUN=${MOVENSYS_PNP_DRY_RUN:-}`),
so just `export` it in the same shell that runs `docker compose`:

```bash
cd docker
export MOVENSYS_PNP_DRY_RUN=1
docker compose up -d --force-recreate
```

Or as a one-off, inline:

```bash
MOVENSYS_PNP_DRY_RUN=1 docker compose -f docker/docker-compose.yml \
    up -d --force-recreate
```