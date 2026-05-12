"""HTTP surface (PRD §5).

Routes are thin: parse request, call GameManager, convert RuleError into
the PRD §4.7 error envelope. Business logic lives in game/*.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
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


@api_router.get("/modes")
async def modes(request: Request) -> dict[str, dict[str, object]]:
    return {
        "stt":   request.app.state.stt_adapter.health(),
        "llm":   request.app.state.llm_adapter.health(),
        "robot": request.app.state.robot_adapter.health(),
    }


# ---- request models --------------------------------------------------------


class StartGameRequest(BaseModel):
    board: Literal["final"]


class DiceSubmitRequest(BaseModel):
    value: int | list[int]
    source: Literal["manual", "rng", "robot"] = "manual"


class DiceRollRobotRequest(BaseModel):
    is_YOLO: bool = True


class MoveApplyRequest(BaseModel):
    player: Literal["user", "robot"]
    from_tile: int = Field(ge=0)
    to_tile: int = Field(ge=0)


class MoveApplyRobotRequest(MoveApplyRequest):
    is_YOLO: bool = True


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


# Default location of the robot pick-and-place script. It now lives next to
# this router under movensys_sample/movensys_robopoly/.
_DEFAULT_PNP_SCRIPT = Path(__file__).resolve().parent / "pick_and_place.py"
_DICE_LINE_RE = re.compile(rb"DICE_NUMBER=(\d+)")

# Board tile index → pick_and_place.py board_positions key. 14-tile board,
# counter-clockwise from GO at bottom-left.
_TILE_INDEX_TO_BOARD_POS: dict[int, str] = {
    0:  "GO",
    1:  "SUWON",
    2:  "SEOUL",
    3:  "IN_JAIL",
    4:  "ELECTRIC_COMPANY",
    5:  "JEONJU",
    6:  "DAEJEON",
    7:  "NON-FREE_PARKING",
    8:  "GYEONGJU",
    9:  "BUSAN",
    10: "GO_TO_JAIL",
    11: "DAEGU",
    12: "CHANCE",
    13: "BUNDANG",
}
_PLAYER_TO_CUBE: dict[str, str] = {"user": "red_cube", "robot": "green_cube"}


@api_router.post("/dice/roll_robot")
async def dice_roll_robot(request: Request, body: DiceRollRobotRequest) -> dict[str, Any]:
    # Spawn pick_and_place.py dice GO <is_YOLO>, return as soon as the script
    # prints DICE_NUMBER=<n> (emitted right after get_piece_info). The physical
    # motion keeps running in the background after we respond.
    script = Path(os.environ.get("MONOPOLY_PNP_SCRIPT", _DEFAULT_PNP_SCRIPT))
    if not script.exists():
        raise HTTPException(
            status_code=500,
            detail={"code": "SCRIPT_NOT_FOUND",
                    "message": f"pick_and_place.py not found at {script}"},
        )

    is_yolo_arg = "true" if body.is_YOLO else "false"
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", str(script), "dice", "GO", is_yolo_arg,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500,
                            detail={"code": "SCRIPT_NOT_FOUND", "message": str(exc)})

    dice_value: int | None = None
    captured: list[bytes] = []
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        captured.append(line)
        m = _DICE_LINE_RE.search(line)
        if m:
            dice_value = int(m.group(1))
            break

    if dice_value is None:
        # Script finished without ever emitting DICE_NUMBER.
        await proc.wait()
        stderr = b""
        if proc.stderr is not None:
            try:
                stderr = await proc.stderr.read()
            except Exception:
                pass
        raise HTTPException(
            status_code=502,
            detail={
                "code": "DICE_NOT_DETECTED",
                "message": "robot did not report a dice number",
                "stdout": b"".join(captured).decode("utf-8", "replace"),
                "stderr": stderr.decode("utf-8", "replace"),
            },
        )

    if not 1 <= dice_value <= 6:
        # Drain & wait so we don't leak the subprocess on bad data.
        asyncio.create_task(_drain_subprocess(proc))
        raise HTTPException(
            status_code=502,
            detail={"code": "DICE_INVALID",
                    "message": f"invalid dice value {dice_value} from robot"},
        )

    # Detach: let the physical pick-and-place finish in the background while
    # we return the rolled value to the caller.
    asyncio.create_task(_drain_subprocess(proc))

    try:
        result = await request.app.state.game.submit_dice(dice_value, "robot")
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))
    result["dice_number"] = dice_value
    return result


async def _drain_subprocess(proc: asyncio.subprocess.Process) -> None:
    """Consume any remaining stdout/stderr and reap the process."""
    try:
        if proc.stdout is not None:
            while await proc.stdout.readline():
                pass
        if proc.stderr is not None:
            await proc.stderr.read()
        await proc.wait()
    except Exception:
        ws_log.exception("drain pick_and_place subprocess failed")


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


@api_router.post("/move/apply_robot")
async def move_apply_robot(request: Request, body: MoveApplyRobotRequest) -> dict[str, Any]:
    # Spawn pick_and_place.py <cube> <board_pos> <is_YOLO> in the background,
    # then apply the game move. The HTTP response waits for the physical motion
    # so the on-screen piece moves at the same moment as the robot.
    board_pos = _TILE_INDEX_TO_BOARD_POS.get(body.to_tile)
    cube = _PLAYER_TO_CUBE.get(body.player)
    if board_pos is None or cube is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "TILE_UNMAPPED",
                    "message": f"no board_pos mapping for tile {body.to_tile} / player {body.player}"},
        )

    script = Path(os.environ.get("MONOPOLY_PNP_SCRIPT", _DEFAULT_PNP_SCRIPT))
    if not script.exists():
        raise HTTPException(
            status_code=500,
            detail={"code": "SCRIPT_NOT_FOUND",
                    "message": f"pick_and_place.py not found at {script}"},
        )

    is_yolo_arg = "true" if body.is_YOLO else "false"
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", str(script), cube, board_pos, is_yolo_arg,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500,
                            detail={"code": "SCRIPT_NOT_FOUND", "message": str(exc)})

    # Wait for the physical pick_and_place to finish before updating the game
    # state. The frontend piece only moves once the robot is on its new tile.
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "PNP_FAILED",
                "message": f"pick_and_place exited with code {proc.returncode}",
                "stdout": stdout.decode("utf-8", "replace"),
                "stderr": stderr.decode("utf-8", "replace"),
            },
        )

    try:
        result = await request.app.state.game.apply_move(body.player, body.from_tile, body.to_tile)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))
    result["robot"] = {"cube": cube, "board_pos": board_pos}
    return result


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


# ---- HTTPException helper --------------------------------------------------


def _http_kwargs(exc: RuleError) -> dict[str, Any]:
    """FastAPI's HTTPException flow cooperates with our error envelope middleware."""
    status = 409 if exc.code in ("TILE_MISMATCH", "INVALID_STATE", "PROPERTY_OWNED",
                                  "NOT_OWNER", "INSUFFICIENT_FUNDS", "MONOPOLY_REQUIRED",
                                  "JAIL_EXIT_UNAVAILABLE") else 400
    if exc.code == "NOT_FOUND":
        status = 404
    return {"status_code": status, "detail": {"code": exc.code, "message": str(exc), "details": exc.details}}
