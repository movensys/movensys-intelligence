"""HTTP surface (PRD §5).

Routes are thin: parse request, call GameManager, convert RuleError into
the PRD §4.7 error envelope. Business logic lives in game/*.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

ws_log = logging.getLogger("monopoly.ws")

from game import RuleError
from utils.logging import current_event_id, new_event_id

api_router = APIRouter(prefix="/api")


# ---- health ---------------------------------------------------------------


@api_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@api_router.get("/robot/health")
async def robot_health(request: Request) -> dict[str, object]:
    return request.app.state.robot_adapter.health()


@api_router.get("/stt/health")
async def stt_health(request: Request) -> dict[str, object]:
    return request.app.state.stt_adapter.health()


@api_router.get("/llm/health")
async def llm_health(request: Request) -> dict[str, object]:
    return request.app.state.llm_adapter.health()


@api_router.get("/ros2/health")
async def ros2_health(request: Request) -> dict[str, object]:
    bridge = request.app.state.ros2
    return {"enabled": bridge.enabled, "isaac_topic": bridge.isaac_card_spawn_topic}


@api_router.get("/_event_id")
async def current_event() -> dict[str, str | None]:
    return {"event_id": current_event_id()}


# ---- error mapping --------------------------------------------------------


def _error_response(exc: RuleError) -> JSONResponse:
    eid = current_event_id() or new_event_id()
    status = 409 if exc.code in ("TILE_MISMATCH", "INVALID_STATE", "PROPERTY_OWNED",
                                  "NOT_OWNER", "INSUFFICIENT_FUNDS", "MONOPOLY_REQUIRED",
                                  "JAIL_EXIT_UNAVAILABLE") else 400
    if exc.code == "NOT_FOUND":
        status = 404
    return JSONResponse(
        status_code=status,
        headers={"X-Event-Id": eid},
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "details": exc.details,
                "event_id": eid,
            }
        },
    )


# ---- request models --------------------------------------------------------


class StartGameRequest(BaseModel):
    board: Literal["1", "2", "3"]


class DiceSubmitRequest(BaseModel):
    value: int | list[int]
    source: Literal["manual", "rng", "robot"] = "manual"


class MoveApplyRequest(BaseModel):
    player: Literal["user", "robot"]
    from_tile: int = Field(ge=0)
    to_tile: int = Field(ge=0)


class ConfigPatch(BaseModel):
    dice_source: Literal["manual", "rng", "robot"] | None = None
    auctions_enabled: bool | None = None
    income_tax_mode: Literal["fixed_200", "choose"] | None = None
    player_colors: dict[str, str] | None = None


# ---- game control ---------------------------------------------------------


@api_router.get("/game/state")
async def game_state(request: Request) -> dict[str, Any]:
    return await request.app.state.game.snapshot()


@api_router.post("/game/start")
async def game_start(request: Request, body: StartGameRequest) -> dict[str, Any]:
    try:
        return await request.app.state.game.start_game(body.board)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/game/end_turn")
async def game_end_turn(request: Request) -> dict[str, Any]:
    try:
        return await request.app.state.game.end_turn()
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.get("/game/winner")
async def game_winner(request: Request) -> dict[str, str | None]:
    return {"winner": request.app.state.game.winner()}


@api_router.post("/game/config")
async def game_config(request: Request, body: ConfigPatch) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    return await request.app.state.game.update_config(patch)


@api_router.get("/game/next_prompt")
async def game_next_prompt(request: Request) -> dict[str, str]:
    # M1 stub; real hint generation lands with Gemma integration at M7.
    state = request.app.state.game.state
    return {
        "hint": f"현재 {state.turn} 턴, FSM={state.fsm.value}. 다음 행동을 지시하세요."
    }


# ---- dice & move ----------------------------------------------------------


@api_router.post("/dice/request")
async def dice_request(request: Request) -> dict[str, Any]:
    try:
        return await request.app.state.game.request_dice()
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/dice/submit")
async def dice_submit(request: Request, body: DiceSubmitRequest) -> dict[str, Any]:
    if isinstance(body.value, list):
        if len(body.value) != 2:
            raise HTTPException(status_code=400, detail="value must be int or [d1, d2]")
        value: int | tuple[int, int] = (body.value[0], body.value[1])
    else:
        value = body.value
    try:
        return await request.app.state.game.submit_dice(value, body.source)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/move/apply")
async def move_apply(request: Request, body: MoveApplyRequest) -> dict[str, Any]:
    try:
        return await request.app.state.game.apply_move(body.player, body.from_tile, body.to_tile)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


# ---- WebSocket stream ------------------------------------------------------


@api_router.websocket("/stream/game")
async def stream_game(ws: WebSocket) -> None:
    """Broadcast FSM/dice/move events to the connected client (PRD §4.6)."""
    await ws.accept()
    bus = ws.app.state.event_bus
    queue = bus.subscribe()
    # Push a hello event so the client can sync immediately.
    from game.events import make_envelope
    await ws.send_json(make_envelope("hello", {"snapshot": ws.app.state.game.state.model_dump()}))
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        ws_log.info("stream_game_disconnect")
    except asyncio.CancelledError:
        raise
    except Exception:
        ws_log.exception("stream_game_error")
    finally:
        bus.unsubscribe(queue)


# ---- HTTPException helper --------------------------------------------------


def _http_kwargs(exc: RuleError) -> dict[str, Any]:
    """FastAPI's HTTPException flow cooperates with our error envelope middleware."""
    status = 409 if exc.code in ("TILE_MISMATCH", "INVALID_STATE", "PROPERTY_OWNED",
                                  "NOT_OWNER", "INSUFFICIENT_FUNDS", "MONOPOLY_REQUIRED",
                                  "JAIL_EXIT_UNAVAILABLE") else 400
    if exc.code == "NOT_FOUND":
        status = 404
    return {"status_code": status, "detail": {"code": exc.code, "message": str(exc), "details": exc.details}}
