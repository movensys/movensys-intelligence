# Movensys Intelligence

Vision-language and speech intelligence layer for the
[`movensys-manipulator`](https://github.com/movensys/movensys-manipulator)
stack. Adds a FastAPI VLM service, a Whisper speech endpoint, a Qdrant
vector memory, optional Phoenix tracing, and sample applications that drive
the manipulator from natural language.

## Overview

This repository sits on top of the WMX R2 manipulator stack and gives it
a higher-level reasoning layer:

- **VLM service** — FastAPI server wrapping a vLLM-hosted Gemma 4 model
  with image input, exposed as REST + WebSocket. It bridges to ROS 2 so it
  can call manipulator services (`MovePose`, `MoveJoints`, `GetEefPose`,
  etc.) directly.
- **Whisper service** — streaming speech-to-text used to issue commands by
  voice.
- **Vector memory** — Qdrant-backed long-term memory for the VLM agent.
- **Sample apps** — `movensys_robopoly`, a board-game demo where the robot
  picks and places pieces under VLM control, with a YOLO + AprilTag
  perception pipeline and a dry-run mode that exercises the full stack
  without moving the arm.

The entire stack runs as a set of Docker compose services and supports
NVIDIA desktop GPUs, Jetson Thor, and Intel B60 / Panther Lake XPU.

## Repository Layout

```
.
├── movensys_vlm/
│   ├── main.py / router.py / ros2_node.py   # FastAPI app + ROS 2 bridge
│   ├── vlm_client.py / whisper_client.py    # vLLM + Whisper clients
│   ├── memory_client.py                     # Qdrant vector memory client
│   ├── models/                              # Local model assets (Gemma, Whisper, embeddings)
│   ├── docker/                              # Compose files: vllm, whisper, vectordb, vlm
│   └── doc/running.md                       # Step-by-step bring-up
└── movensys_sample/
    └── movensys_robopoly/                   # Board-game demo (FastAPI + adapters)
        ├── main.py / router.py
        ├── pick_and_place.py
        ├── adapters/                        # robot, ros_image, stt, vlm
        ├── game/                            # rules, manager, decks, boards
        ├── scripts/                         # auto_play_dry_run, render helpers
        └── docker/                          # Compose stack
```

## Services and Ports

| Service                | Default port | Purpose                                  |
|------------------------|--------------|------------------------------------------|
| `movensys_vlm` (FastAPI) | 8000       | VLM REST/WebSocket API + ROS 2 bridge    |
| `vllm`                  | 9000        | vLLM OpenAI-compatible inference server |
| `whisper`               | 9010        | Speech-to-text server                    |
| `vectordb` (Qdrant)     | 6333        | Long-term vector memory                  |
| `embed` (TEI)           | 9020        | Text embeddings for the vector memory    |
| `movensys_robopoly`     | 7999        | Robopoly demo UI/API                     |
| `phoenix` (optional)    | 6006        | OpenTelemetry/LLM traces UI              |

## Requirements

- Ubuntu 22.04 or 24.04
- Docker with `docker compose`
- Hardware: NVIDIA GPU (desktop or Jetson Thor) or Intel XPU (B60 / Panther Lake)
- Local model weights placed under `movensys_vlm/models/` (Gemma 4 E2B/E4B, Whisper large-v3, embedding model)
- The [`movensys-manipulator`](https://github.com/movensys/movensys-manipulator) stack running (the VLM publishes/calls its ROS 2 services)

## Quick Start

### 1. Configure the host environment

Add the following to your `~/.bashrc`:

```
export XPU_CORE=nvidia-gpu        # {nvidia-gpu, intel-xpu}
export CPU_ARCH=amd64             # {amd64, arm64}
```

```
source ~/.bashrc
```

### 2. Clone the repository

```
mkdir -p ~/workspaces
cd ~/workspaces
git clone https://github.com/movensys/movensys-intelligence.git
```

### 3. Start the VLM stack

For Nvidia desktop, Jetson Thor, or Intel B60:

```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
COMPOSE_PROFILES=$XPU_CORE docker compose -f vllm.yaml up -d --build
COMPOSE_PROFILES=$CPU_ARCH docker compose -f vectordb.yaml up -d --build
COMPOSE_PROFILES=$XPU_CORE docker compose -f whisper.yaml up -d --build
COMPOSE_PROFILES=$XPU_CORE docker compose -f movensys_vlm.yaml up -d --build
```

For Intel Panther Lake (vLLM uses a separate build path):

```
cd ~/workspaces/movensys-intelligence/movensys_vlm/docker
./vllm-intel-build.sh
./vllm-intel-run.sh
```

Wait for `application startup complete` in the vLLM logs before continuing.

> On Jetson Thor or Intel Panther Lake, drop kernel caches between restarts
> if memory pressure builds up:
> `sync && sudo sysctl vm.drop_caches=3`

Full bring-up, teardown, and Phoenix-tracing options are documented in
[`movensys_vlm/doc/running.md`](movensys_vlm/doc/running.md).

### 4. Run a sample application

The Robopoly board-game demo drives the manipulator via the VLM stack. With
the `movensys-manipulator` YOLO simulation example running (see
[`movensys-manipulator/doc/8a_yolo_simulation.md`](https://github.com/movensys/movensys-manipulator/blob/main/doc/8a_yolo_simulation.md)):

```
export MOVENSYS_PNP_DRY_RUN=0     # set to 1 to skip arm motion
cd ~/workspaces/movensys-intelligence/movensys_sample/movensys_robopoly/docker
docker compose up -d --build
```

Open the UI on `http://localhost:7999/`, toggle `is_YOLO` on, and start a
game. Dry-run mode and the auto-play test script are described in
[`movensys_sample/doc/1a_robopoly_simulation.md`](movensys_sample/doc/1a_robopoly_simulation.md),
and the real-robot run in
[`movensys_sample/doc/1c_robopoly_real.md`](movensys_sample/doc/1c_robopoly_real.md).

Robopoly's own reference docs live in
[`movensys_sample/movensys_robopoly/doc/`](movensys_sample/movensys_robopoly/doc/):

| Doc | Covers |
|-----|--------|
| [`running.md`](movensys_sample/movensys_robopoly/doc/running.md) | Bring-up, environment variables, dry-run mode |
| [`API.md`](movensys_sample/movensys_robopoly/doc/API.md) | REST/WebSocket endpoints |
| [`game_logic.md`](movensys_sample/movensys_robopoly/doc/game_logic.md) | Board rules, decks, turn handling |
| [`vlm_as_player.md`](movensys_sample/movensys_robopoly/doc/vlm_as_player.md) | How the VLM takes a turn |
| [`PRD.md`](movensys_sample/movensys_robopoly/doc/PRD.md) | Product requirements for the demo |

### Pick-and-place from the command line

```
cd ~/workspaces/movensys-intelligence
python3 movensys_sample/movensys_robopoly/pick_and_place.py red_cube GO true 2>&1 | tee baseline.log
grep '\[timing\]' baseline.log
```

## Related Repositories

- [movensys-manipulator](https://github.com/movensys/movensys-manipulator) — ROS 2 manipulator stack driven by this layer
- [movensys-simulation](https://github.com/movensys/movensys-simulation) — Isaac Sim scenes used by the demos
- [wmx-r2](https://github.com/movensys/wmx-r2) — Core WMX motion control packages
- [wmx-r2-doc](https://github.com/movensys/wmx-r2-doc) — WMX R2 documentation site

## License

Released under the MIT License. See [`LICENSE.txt`](LICENSE.txt) for details.
