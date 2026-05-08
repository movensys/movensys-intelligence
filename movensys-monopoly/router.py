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
    return {
        "enabled": bridge.enabled,
        "cameras_enabled": getattr(bridge, "cameras_enabled", False),
    }


@api_router.get("/modes")
async def modes(request: Request) -> dict[str, dict[str, object]]:
    """Aggregate adapter status. Fetched once by the UI at page load
    instead of polling each /*/health endpoint on an interval — the
    values are set in lifespan() from env and don't change during a
    session, so periodic polling just burns log lines and sockets.
    Individual /*/health endpoints are kept for curl-level drill-down."""
    bridge = request.app.state.ros2
    return {
        "stt":   request.app.state.stt_adapter.health(),
        "llm":   request.app.state.llm_adapter.health(),
        "robot": request.app.state.robot_adapter.health(),
        "ros2": {
            "enabled": bridge.enabled,
            "cameras_enabled": getattr(bridge, "cameras_enabled", False),
        },
    }


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


class DecideRequest(BaseModel):
    action: Literal["skip", "buy", "build"]
    house_count: int = Field(default=0, ge=0, le=5)


class BuildRequest(BaseModel):
    houses: int = Field(default=1, ge=0, le=4)
    hotel: bool = False


class EffectRequest(BaseModel):
    player: Literal["user", "robot"]
    # Any additional keys go through as effect args
    model_config = {"extra": "allow"}


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


# ---- property -------------------------------------------------------------


@api_router.get("/properties")
async def properties(request: Request) -> list[dict[str, Any]]:
    return request.app.state.game.list_properties()


@api_router.get("/properties/{pid}")
async def property_detail(request: Request, pid: str) -> dict[str, Any]:
    cards = {c["id"]: c for c in request.app.state.game.list_properties()}
    if pid not in cards:
        raise HTTPException(status_code=404,
                            detail={"code": "NOT_FOUND", "message": f"unknown property {pid}"})
    return cards[pid]


@api_router.post("/properties/{pid}/decide")
async def property_decide(request: Request, pid: str, body: DecideRequest) -> dict[str, Any]:
    game = request.app.state.game
    player = game.state.turn
    try:
        return await game.decide_property(player, pid, body.action, body.house_count)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/properties/{pid}/buy")
async def property_buy(request: Request, pid: str) -> dict[str, Any]:
    game = request.app.state.game
    try:
        return await game.buy_property(game.state.turn, pid)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/properties/{pid}/build")
async def property_build(request: Request, pid: str, body: BuildRequest) -> dict[str, Any]:
    game = request.app.state.game
    try:
        return await game.build(game.state.turn, pid, houses=body.houses, hotel=body.hotel)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/properties/{pid}/mortgage")
async def property_mortgage(request: Request, pid: str) -> dict[str, Any]:
    game = request.app.state.game
    try:
        return await game.mortgage(game.state.turn, pid)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/properties/{pid}/unmortgage")
async def property_unmortgage(request: Request, pid: str) -> dict[str, Any]:
    game = request.app.state.game
    try:
        return await game.unmortgage(game.state.turn, pid)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


@api_router.post("/properties/{pid}/sell_building")
async def property_sell_building(request: Request, pid: str) -> dict[str, Any]:
    game = request.app.state.game
    try:
        return await game.sell_building(game.state.turn, pid)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))


# ---- money ---------------------------------------------------------------


@api_router.get("/money")
async def money_snapshot(request: Request) -> dict[str, int]:
    return request.app.state.game.money_snapshot()


@api_router.get("/money/{player}")
async def money_player(request: Request, player: Literal["user", "robot"]) -> dict[str, Any]:
    snap = request.app.state.game.money_snapshot()
    if player not in snap:
        raise HTTPException(status_code=404,
                            detail={"code": "NOT_FOUND", "message": f"unknown player {player}"})
    return {"player": player, "balance": snap[player]}


# ---- effects (Chance/CC callable for debugging) --------------------------


@api_router.post("/effects/{effect_type}")
async def effects_apply(request: Request, effect_type: str, body: EffectRequest) -> dict[str, Any]:
    from game.effects import EffectError
    game = request.app.state.game
    payload = body.model_dump(exclude={"player"})
    payload["type"] = effect_type
    try:
        return await game.apply_card_effect(body.player, payload)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))
    except EffectError as exc:
        raise HTTPException(status_code=400,
                            detail={"code": exc.code, "message": str(exc)})


# ---- WebSocket stream ------------------------------------------------------


async def _stream_events(ws: WebSocket, name: str, type_filter: set[str] | None = None) -> None:
    """Shared WS subscriber used by /stream/{game,board,money,properties}.
    When `type_filter` is set the stream only forwards envelopes whose
    `type` matches. /stream/game forwards everything (PRD §4.6)."""
    await ws.accept()
    bus = ws.app.state.event_bus
    queue = bus.subscribe()
    from game.events import make_envelope
    await ws.send_json(make_envelope("hello", {
        "stream": name,
        "snapshot": ws.app.state.game.state.model_dump(),
    }))
    try:
        while True:
            event = await queue.get()
            if type_filter is None or event["type"] in type_filter:
                await ws.send_json(event)
    except WebSocketDisconnect:
        ws_log.info("stream_%s_disconnect", name)
    except asyncio.CancelledError:
        raise
    except Exception:
        ws_log.exception("stream_%s_error", name)
    finally:
        bus.unsubscribe(queue)


@api_router.websocket("/stream/game")
async def stream_game(ws: WebSocket) -> None:
    await _stream_events(ws, "game")


@api_router.websocket("/stream/board")
async def stream_board(ws: WebSocket) -> None:
    await _stream_events(ws, "board", {"move_applied", "lap_completed", "fsm_transition",
                                        "game_started", "game_won"})


@api_router.websocket("/stream/money")
async def stream_money(ws: WebSocket) -> None:
    await _stream_events(ws, "money", {"effect_applied", "property_bought",
                                        "property_built", "property_mortgaged",
                                        "property_unmortgaged", "building_sold",
                                        "tile_rent_paid", "tile_tax_paid",
                                        "tile_rent_bankruptcy", "tile_tax_bankruptcy"})


@api_router.websocket("/stream/properties")
async def stream_properties(ws: WebSocket) -> None:
    await _stream_events(ws, "properties", {"property_bought", "property_built",
                                             "property_mortgaged", "property_unmortgaged",
                                             "building_sold"})


# ---- Camera proxies (PRD §5.8, §11.5) -------------------------------------


async def _ws_camera_stream(ws: WebSocket, stream: str, interval: float = 0.1) -> None:
    """Poll the ROS bridge at `interval` seconds and ship the latest
    encoded frame. Envelope matches movensys_vlm so the shared cameras.html
    renders without changes: `{data, error}` with error set to a short
    string when no frame has arrived yet."""
    import json
    await ws.accept()
    bridge = ws.app.state.ros2
    try:
        while True:
            data = bridge.latest_frame(stream) if bridge.enabled else None
            await ws.send_text(json.dumps(
                {"data": data, "error": None if data is not None else "No data"}
            ))
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        ws_log.info("stream_%s_disconnect", stream)
    except asyncio.CancelledError:
        raise
    except Exception:
        ws_log.exception("stream_%s_error", stream)


@api_router.websocket("/stream/image_top/rgb")
async def ws_top_rgb(ws: WebSocket) -> None:
    await _ws_camera_stream(ws, "top_rgb")


@api_router.websocket("/stream/image_top/depth")
async def ws_top_depth(ws: WebSocket) -> None:
    await _ws_camera_stream(ws, "top_depth")


@api_router.websocket("/stream/image_top/camera_info")
async def ws_top_info(ws: WebSocket) -> None:
    await _ws_camera_stream(ws, "top_camera_info", interval=1.0)


@api_router.websocket("/stream/image_hand/rgb")
async def ws_hand_rgb(ws: WebSocket) -> None:
    await _ws_camera_stream(ws, "hand_rgb")


@api_router.websocket("/stream/image_hand/depth")
async def ws_hand_depth(ws: WebSocket) -> None:
    await _ws_camera_stream(ws, "hand_depth")


@api_router.websocket("/stream/image_hand/camera_info")
async def ws_hand_info(ws: WebSocket) -> None:
    await _ws_camera_stream(ws, "hand_camera_info", interval=1.0)


def _topic_snapshot(request: Request, stream: str) -> dict[str, Any]:
    bridge = request.app.state.ros2
    if not bridge.enabled:
        raise HTTPException(status_code=503,
                            detail={"code": "ADAPTER_UNAVAILABLE",
                                    "message": "ROS 2 bridge not running"})
    data = bridge.latest_frame(stream)
    if data is None:
        raise HTTPException(status_code=503,
                            detail={"code": "ADAPTER_UNAVAILABLE",
                                    "message": f"no frame yet for {stream}"})
    return data


@api_router.get("/topics/image_top/rgb")
async def topic_top_rgb(request: Request) -> dict[str, Any]:
    return _topic_snapshot(request, "top_rgb")


@api_router.get("/topics/image_top/depth")
async def topic_top_depth(request: Request) -> dict[str, Any]:
    return _topic_snapshot(request, "top_depth")


@api_router.get("/topics/image_top/camera_info")
async def topic_top_info(request: Request) -> dict[str, Any]:
    return _topic_snapshot(request, "top_camera_info")


@api_router.get("/topics/image_hand/rgb")
async def topic_hand_rgb(request: Request) -> dict[str, Any]:
    return _topic_snapshot(request, "hand_rgb")


@api_router.get("/topics/image_hand/depth")
async def topic_hand_depth(request: Request) -> dict[str, Any]:
    return _topic_snapshot(request, "hand_depth")


@api_router.get("/topics/image_hand/camera_info")
async def topic_hand_info(request: Request) -> dict[str, Any]:
    return _topic_snapshot(request, "hand_camera_info")


# ---- HTTPException helper --------------------------------------------------


def _http_kwargs(exc: RuleError) -> dict[str, Any]:
    """FastAPI's HTTPException flow cooperates with our error envelope middleware."""
    status = 409 if exc.code in ("TILE_MISMATCH", "INVALID_STATE", "PROPERTY_OWNED",
                                  "NOT_OWNER", "INSUFFICIENT_FUNDS", "MONOPOLY_REQUIRED",
                                  "JAIL_EXIT_UNAVAILABLE") else 400
    if exc.code == "NOT_FOUND":
        status = 404
    return {"status_code": status, "detail": {"code": exc.code, "message": str(exc), "details": exc.details}}
