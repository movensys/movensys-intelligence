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
python3 -m uvicorn main:app --host 127.0.0.1 --port 7999
```

> Bind to `127.0.0.1` (not `0.0.0.0`). The browser requires a secure
> origin to grant `getUserMedia()` mic access — `http://localhost:*`
> and `http://127.0.0.1:*` qualify; `http://0.0.0.0:*` and
> `http://<lan-ip>:*` do not. Open the UI at `http://localhost:7999/`.

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

The compose file bind-mounts the working-copy source (`main.py`,
`router.py`, `pick_and_place.py`, `adapters/`, `game/`, `static/`,
`doc/`, `saved_status.yaml`) into `/app` inside the container. That
means **edits on the host are picked up on the next container restart**
— you do **not** need to `docker compose build` for source changes. Only
rebuild when `requirements.txt` or the `Dockerfile` itself changes.

### Run (full clean cycle)

```bash
export MOVENSYS_PNP_DRY_RUN=1   # optional — skips real robot motion
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build            # only needed when deps/Dockerfile change
docker compose up -d               # foreground; Ctrl-C to stop
```

Detached variant (matches `run.sh`):

```bash
docker compose up -d --force-recreate
```

### Logs

```bash
docker compose logs -f
```

### Pick up source changes without rebuild

```bash
docker compose restart          # re-execs uvicorn against the mounted /app
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
export MOVENSYS_PNP_DRY_RUN=0
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose down
docker compose build
docker compose up -d
```

```bash
amixer -c 1 cset numid=4 40
alsamixer # hardare/driver layer
```

Or as a one-off, inline:

```bash
MOVENSYS_PNP_DRY_RUN=1 docker compose -f docker/docker-compose.yml \
    up -d --force-recreate
```
