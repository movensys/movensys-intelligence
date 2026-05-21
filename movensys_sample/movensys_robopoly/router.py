"""HTTP surface (PRD §5).

Routes are thin: parse request, call GameManager, convert RuleError into
the PRD §4.7 error envelope. Business logic lives in game/*.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
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


@api_router.get("/vlm/health")
async def vlm_health(request: Request) -> dict[str, object]:
    return request.app.state.vlm_adapter.health()


@api_router.get("/modes")
async def modes(request: Request) -> dict[str, dict[str, object]]:
    return {
        "stt":   request.app.state.stt_adapter.health(),
        "vlm":   request.app.state.vlm_adapter.health(),
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
    is_YOLO: bool | None = None


class DecideRequest(BaseModel):
    action: Literal["skip", "buy", "build", "build_hotel"]
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


_SAVED_STATE_PATH = Path(__file__).resolve().parent / "saved_status.yaml"


@api_router.post("/game/save_state")
async def game_save_state(request: Request) -> dict[str, Any]:
    # mode="json" so enums (FSM) and tuples become primitives PyYAML can handle.
    snapshot = request.app.state.game.state.model_dump(mode="json")
    try:
        with open(_SAVED_STATE_PATH, "w", encoding="utf-8") as fh:
            yaml.safe_dump(snapshot, fh, sort_keys=False, allow_unicode=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "SAVE_FAILED", "message": str(exc)},
        )
    return {"path": str(_SAVED_STATE_PATH), "ok": True}


@api_router.post("/game/load_state")
async def game_load_state(request: Request) -> dict[str, Any]:
    if not _SAVED_STATE_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail={"code": "NO_SAVED_STATE",
                    "message": f"no saved state at {_SAVED_STATE_PATH}"},
        )
    try:
        with open(_SAVED_STATE_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "LOAD_FAILED", "message": str(exc)},
        )
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_SAVED_STATE",
                    "message": "saved_status.yaml is not a mapping"},
        )
    try:
        new_state = await request.app.state.game.replace_state(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_SAVED_STATE", "message": str(exc)},
        )
    return {"path": str(_SAVED_STATE_PATH), "ok": True, "state": new_state}


@api_router.get("/game/next_prompt")
async def game_next_prompt(request: Request) -> dict[str, str]:
    # M1 stub; real hint generation lands with Gemma integration at M7.
    state = request.app.state.game.state
    return {
        "hint": f"현재 {state.turn} 턴, FSM={state.fsm.value}. 다음 행동을 지시하세요."
    }


_RULES_PATH = Path(__file__).resolve().parent / "doc" / "game_logic.md"


@api_router.get("/game/rules")
async def game_rules() -> "PlainTextResponse":
    """Return the authoritative game spec as raw markdown. Used by the
    VLM-player agent loop to seed the system prompt with the rules at
    boot (see doc/vlm_as_player.md §3)."""
    from fastapi.responses import PlainTextResponse
    if not _RULES_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail={"code": "NO_RULES_DOC",
                    "message": f"rules doc not found at {_RULES_PATH}"},
        )
    try:
        text = _RULES_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "RULES_READ_FAILED", "message": str(exc)},
        )
    return PlainTextResponse(text, media_type="text/markdown")


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
# pick_and_place.py prints this sentinel on its own line right after
# get_piece_info / _search_for_target succeeds. The spawning route
# forwards it as a `yolo_detection_done` WS event so the frontend
# overlay closes early — operator sees the board during the physical
# pick-and-place instead of staring at a frozen YOLO frame.
_YOLO_DETECTED_SENTINEL = b"YOLO_DETECTED"

# Board tile index → pick_and_place.py board_positions key. 14-tile board,
# counter-clockwise from GO at bottom-left (Board3_v2).
_TILE_INDEX_TO_BOARD_POS: dict[int, str] = {
    0:  "GO",
    1:  "BOSTON",
    2:  "SEOUL",
    3:  "DESERT_ISLAND",
    4:  "ELECTRIC_COMPANY",
    5:  "TAIPEI",
    6:  "SHANGHAI",
    7:  "NON-FREE_PARKING",
    8:  "TOKYO",
    9:  "BUSAN",
    10: "GO_TO_DESERT_ISLAND",
    11: "NEW_YORK",
    12: "CHANCE",
    13: "LONDON",
}
_PLAYER_TO_CUBE: dict[str, str] = {"user": "red_cube", "robot": "green_cube"}


async def _spawn_dice_subprocess(
    request: Request,
    body: DiceRollRobotRequest,
    mode: str,
    source: str,
) -> dict[str, Any]:
    """Shared body for /dice/{roll,read}_robot.

    mode="roll" runs the full pick-and-drop chain (robot turn);
    mode="read" only moves the arm to the dice scan pose so YOLO can see
    the human-thrown face (user turn). `source` is forwarded to
    game.submit_dice — "robot" or "manual".
    """
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
            "python3", str(script), "dice", "GO", is_yolo_arg, mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500,
                            detail={"code": "SCRIPT_NOT_FOUND", "message": str(exc)})

    dice_value: int | None = None
    captured: list[bytes] = []
    yolo_emitted = False
    bus = request.app.state.game.bus
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        captured.append(line)
        if not yolo_emitted and _YOLO_DETECTED_SENTINEL in line:
            bus.publish_nowait("yolo_detection_done", {"kind": "dice"})
            yolo_emitted = True
        m = _DICE_LINE_RE.search(line)
        if m:
            dice_value = int(m.group(1))
            break

    if dice_value is None:
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
        asyncio.create_task(_drain_subprocess(proc))
        raise HTTPException(
            status_code=502,
            detail={"code": "DICE_INVALID",
                    "message": f"invalid dice value {dice_value} from robot"},
        )

    # Detach: roll mode still has the physical pick-and-place finishing;
    # read mode is essentially done. Either way, drain in background.
    asyncio.create_task(_drain_subprocess(proc))

    try:
        result = await request.app.state.game.submit_dice(dice_value, source)
    except RuleError as exc:
        raise HTTPException(**_http_kwargs(exc))
    result["dice_number"] = dice_value
    return result


@api_router.post("/dice/read_robot")
async def dice_read_robot(request: Request, body: DiceRollRobotRequest) -> dict[str, Any]:
    """User-turn dice path: the human has rolled the die by hand. The arm
    moves to the dice scan pose so the camera has a clear view, YOLO is
    read, and the value is submitted as source="manual". No pickup, no
    drop — see pick_and_place._read_dice_only.
    """
    return await _spawn_dice_subprocess(request, body, mode="read", source="manual")


@api_router.post("/dice/roll_robot")
async def dice_roll_robot(request: Request, body: DiceRollRobotRequest) -> dict[str, Any]:
    """Robot-turn dice path: arm physically picks up, drops, and reads."""
    return await _spawn_dice_subprocess(request, body, mode="roll", source="robot")


# ---- chance card (VLM-driven) --------------------------------------------

# Four fixed chance-card outcomes the game supports. The VLM reads a
# physical card and the second VLM call maps the reading to one of
# these four — there are no other possible outcomes.
_CHANCE_CHOICES = ("-150", "0_sorry", "100", "200")
_CHANCE_DELTA: dict[str, int] = {"-150": -150, "0_sorry": 0, "100": 100, "200": 200}
_CHANCE_LABEL: dict[str, str] = {
    "-150":    "-$150",
    "0_sorry": "$0 (sorry)",
    "100":     "+$100",
    "200":     "+$200",
}
# Token-conscious prompts: the orchestrator pays per token on both
# input AND output and we run this flow every chance card. Both prompts
# stay under ~80 tokens; max_tokens is capped hard in the request body.
_CHANCE_READ_PROMPT = (
    "Read the dollar amount on this chance card.\n"
    "Reply with ONLY digits with a sign prefix and a dollar sign. "
    'Examples: "-$150", "$200", "$0", "$100".\n'
    "NEVER spell numbers as words. NEVER add prose."
)
_CHANCE_SYSTEM_PROMPT = (
    "Pick ONE of four chance outcomes for the dollar amount in the user message:\n"
    '  "-150"     if the card is negative (player pays $150)\n'
    '  "200"      if the card is +$200\n'
    '  "100"      if the card is +$100\n'
    '  "0_sorry"  if the card is $0 or says sorry\n'
    'Reply ONLY: {"choice":"-150"|"0_sorry"|"100"|"200"}'
)
_CHANCE_POPUP_HOLD_S = 2.0
# Regex fallback for the decision step: scan the raw reply for one of the
# four canonical tokens. Order matters — "-150" must beat "150".
_CHANCE_CHOICE_RE = re.compile(r"(-150|0_sorry|200|100|\bsorry\b|\b0\b)", re.IGNORECASE)


def _parse_chance_choice(raw: str) -> str:
    """Extract one of the four allowed outcomes from a VLM reply. Tries
    strict JSON first, then falls back to a regex over the raw text.
    Defaults to "0_sorry" (no-op) if nothing matches, so the flow always
    advances even when the model goes off-script.
    """
    text = (raw or "").strip()
    if not text:
        return "0_sorry"
    # Try strict JSON (handles ```json … ``` fences too)
    fenced = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text, flags=re.IGNORECASE)
    try:
        obj = _json.loads(fenced)
        choice = str(obj.get("choice", "")).strip()
        if choice in _CHANCE_CHOICES:
            return choice
    except (_json.JSONDecodeError, AttributeError):
        pass
    # Regex fallback over the whole reply
    m = _CHANCE_CHOICE_RE.search(text)
    if m:
        token = m.group(1).lower()
        if token in _CHANCE_CHOICES:
            return token
        if token in ("sorry", "0"):
            return "0_sorry"
    return "0_sorry"


async def _run_chance_init_subprocess(is_yolo: bool) -> None:
    """Spawn pick_and_place.py in chance_init mode: park the arm at the
    cube-detection scan pose, sleep 2 s, exit. Raises HTTPException on
    subprocess failure so the caller surfaces the same error envelope as
    the other PnP routes.
    """
    script = Path(os.environ.get("MONOPOLY_PNP_SCRIPT", _DEFAULT_PNP_SCRIPT))
    if not script.exists():
        raise HTTPException(
            status_code=500,
            detail={"code": "SCRIPT_NOT_FOUND",
                    "message": f"pick_and_place.py not found at {script}"},
        )
    is_yolo_arg = "true" if is_yolo else "false"
    # target_object is required by PnP.__init__ but the chance_init mode
    # never touches the YOLO topic — any non-dice cube name works. Pick
    # red_cube (the user's piece) so the validator passes.
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", str(script), "red_cube", "GO", is_yolo_arg, "chance_init",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500,
                            detail={"code": "SCRIPT_NOT_FOUND", "message": str(exc)})
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "PNP_FAILED",
                "message": f"chance_init pick_and_place exited with {proc.returncode}",
                "stdout": stdout.decode("utf-8", "replace"),
                "stderr": stderr.decode("utf-8", "replace"),
            },
        )


async def _vlm_infer(
    *, prompt: str, camera: str, system_prompt: str | None = None,
    max_tokens: int = 128, temperature: float = 0.0,
) -> str:
    """POST {MOVENSYS_VLM_URL}/api/vlm/infer and return the raw response
    text. The orchestrator proxies to vLLM (:9000); we keep the call
    inline rather than going through VLMAdapter because the adapter's
    system prompt is hard-coded to an intent classifier.
    """
    base = os.environ.get("MOVENSYS_VLM_URL", "http://localhost:8000").strip()
    if not base:
        raise HTTPException(
            status_code=503,
            detail={"code": "VLM_OFFLINE",
                    "message": "MOVENSYS_VLM_URL is not set — VLM in stub mode"},
        )
    body: dict[str, Any] = {
        "camera": camera,
        "prompt": prompt,
        "client": "robopoly_chance",
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_prompt:
        body["system_prompt"] = system_prompt
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{base}/api/vlm/infer", json=body)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "VLM_REQUEST_FAILED", "message": str(exc)},
        )
    if data.get("error"):
        raise HTTPException(
            status_code=502,
            detail={"code": "VLM_ERROR", "message": str(data.get("error"))},
        )
    return str(data.get("response") or "").strip()


@api_router.post("/game/chance_card")
async def game_chance_card(request: Request) -> dict[str, Any]:
    """Run the VLM-driven chance card flow for the current turn player.

    Fired either by (a) the tile-arrival deferred resolution (chance tile
    12) or (b) the frontend V-key hotkey on the user's TURN_START. The
    flow is the same for both:
      1. arm → cube scan pose, settle 2 s
      2. VLM call 1 ("read this card") on the top camera frame
      3. publish chance_card_read, hold popup 2 s
      4. VLM call 2 — pick one of -100/+200/0/+100 from the read text
      5. apply the money delta to the current player's balance
      6. publish chance_card_applied, hold popup 2 s
    """
    game = request.app.state.game
    player = game.state.turn
    is_yolo = bool(getattr(game.state.config, "is_YOLO", True))

    # 1. Park the arm so the top camera has a clean view of the card.
    await _run_chance_init_subprocess(is_yolo)

    # 2. VLM read — arm is at the cube-scan pose so the gripper-mounted
    #    ("hand") camera is the one pointing down at the card. max_tokens
    #    is tight (24) because the expected reply is at most 6 chars
    #    ("-$150"); anything longer is prose we'd discard anyway.
    try:
        read_text = await _vlm_infer(
            prompt=_CHANCE_READ_PROMPT,
            camera="hand",
            max_tokens=24,
            temperature=0.0,
        )
    except HTTPException:
        raise
    if not read_text:
        read_text = "(VLM returned no text for the card)"

    # 3. Tell the UI to flash the read text in the chat / overlay.
    game.bus.publish_nowait("chance_card_read", {
        "player": player,
        "text": read_text,
        "hold_s": _CHANCE_POPUP_HOLD_S,
    })
    await asyncio.sleep(_CHANCE_POPUP_HOLD_S)

    # 4. Decision call — small system prompt forces a 1-of-4 outcome.
    decision_prompt = (
        f"Read this card and consider it to the game.\n"
        f"Card text: {read_text!r}\n"
        f'Return JSON: {{"choice": "-100"|"+200"|"0"|"+100"}}.'
    )
    decision_raw = await _vlm_infer(
        prompt=decision_prompt,
        camera="none",
        system_prompt=_CHANCE_SYSTEM_PROMPT,
        max_tokens=64,
        temperature=0.0,
    )
    choice = _parse_chance_choice(decision_raw)
    delta = _CHANCE_DELTA[choice]

    # 5. Apply the money change to the current turn player's liquid balance.
    #    No bankruptcy chain here (the deltas are tiny relative to seed
    #    money / typical balances) — just clamp at 0 on a pay outcome.
    async with game._lock:
        p_state = game.state.players.get(player)
        if p_state is not None:
            if delta > 0:
                p_state.balance += delta
            elif delta < 0:
                p_state.balance = max(0, p_state.balance + delta)
        new_balance = p_state.balance if p_state is not None else 0

    # 6. Result popup — frontend listens for chance_card_applied to flash
    #    "{player}: -$100" etc. and updates the money widget via state refresh.
    game.bus.publish_nowait("chance_card_applied", {
        "player": player,
        "choice": choice,
        "label": _CHANCE_LABEL[choice],
        "delta": delta,
        "balance": new_balance,
        "card_text": read_text,
        "raw_decision": decision_raw,
        "hold_s": _CHANCE_POPUP_HOLD_S,
    })
    await asyncio.sleep(_CHANCE_POPUP_HOLD_S)

    return {
        "player": player,
        "card_text": read_text,
        "choice": choice,
        "label": _CHANCE_LABEL[choice],
        "delta": delta,
        "balance": new_balance,
    }


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
    # We read stdout line-by-line (instead of a single communicate()) so the
    # YOLO_DETECTED sentinel can fire a WS event mid-subprocess and the
    # frontend overlay closes the moment detection completes.
    stdout_lines: list[bytes] = []
    yolo_emitted = False
    bus = request.app.state.game.bus
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        stdout_lines.append(line)
        if not yolo_emitted and _YOLO_DETECTED_SENTINEL in line:
            bus.publish_nowait("yolo_detection_done", {"kind": "cube"})
            yolo_emitted = True
    await proc.wait()
    stdout = b"".join(stdout_lines)
    stderr = b""
    if proc.stderr is not None:
        try:
            stderr = await proc.stderr.read()
        except Exception:
            pass
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

    # Spec §4.5.1: landing on GO_TO_DESERT_ISLAND teleports the player's
    # position to DESERT_ISLAND in-engine; physically move the cube there
    # too so the board state matches the game state.
    jail_resolved = next(
        (r for r in result.get("resolved", {}).get("tiles", [])
         if r.get("kind") == "go_to_jail"),
        None,
    )
    if jail_resolved is not None:
        jail_pnp = await _pick_and_place_to_jail(script, cube, body.is_YOLO)
        result["robot_jail"] = jail_pnp
    return result


async def _pick_and_place_to_jail(
    script: Path, cube: str, is_yolo: bool,
) -> dict[str, Any]:
    """Run pick_and_place.py <cube> DESERT_ISLAND <is_YOLO> for the §4.5.1
    auto-jail move. Raises HTTPException on subprocess failure so the
    caller sees the same error envelope as the primary apply_robot path.
    """
    is_yolo_arg = "true" if is_yolo else "false"
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", str(script), cube, "DESERT_ISLAND", is_yolo_arg,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500,
                            detail={"code": "SCRIPT_NOT_FOUND", "message": str(exc)})
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "PNP_JAIL_FAILED",
                "message": f"jail pick_and_place exited with code {proc.returncode}",
                "stdout": stdout.decode("utf-8", "replace"),
                "stderr": stderr.decode("utf-8", "replace"),
            },
        )
    return {"cube": cube, "board_pos": "DESERT_ISLAND"}


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


# Voluntary mortgage / unmortgage / sell_building routes are intentionally
# removed (spec §5.1: no voluntary selling). The only sell path is
# auto-liquidation, which is internal to rules.py.


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
                                        "property_built", "tier_sold",
                                        "tile_rent_paid", "tile_tax_paid",
                                        "tile_rent_bankruptcy", "tile_tax_bankruptcy"})


@api_router.websocket("/stream/properties")
async def stream_properties(ws: WebSocket) -> None:
    await _stream_events(ws, "properties", {"property_bought", "property_built",
                                             "tier_sold"})


# ---- YOLO debug image streams ---------------------------------------------
#
# The static UI swaps the board pane for these streams while a
# pick_and_place subprocess is in flight (see static/app.js
# `withYoloStream`). Images are sourced from the rclpy subscriber spun up
# in main.py lifespan; if rclpy is unavailable the latest frame stays
# None and the WS keeps sending {data: null, error: "No data"}.

async def _stream_image(ws: WebSocket, attr: str, interval: float = 0.1) -> None:
    import json as _json
    await ws.accept()
    try:
        while True:
            ros_image = getattr(ws.app.state, "ros_image", None)
            data = getattr(ros_image, attr, None) if ros_image is not None else None
            await ws.send_text(_json.dumps({
                "data": data,
                "error": None if data is not None else "No frame yet",
            }))
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return
    except Exception:
        ws_log.exception("stream_image_%s_error", attr)


@api_router.websocket("/stream/yolo_dice_detector/debug_image")
async def stream_yolo_dice_debug(ws: WebSocket) -> None:
    await _stream_image(ws, "latest_dice_debug")


@api_router.websocket("/stream/yolo_cube_detector/debug_image")
async def stream_yolo_cube_debug(ws: WebSocket) -> None:
    await _stream_image(ws, "latest_cube_debug")


@api_router.websocket("/stream/image_hand/rgb")
async def stream_image_hand_rgb(ws: WebSocket) -> None:
    """Raw gripper-mounted camera RGB. Used by the chance-card overlay so
    the operator can see the card the VLM is reading."""
    await _stream_image(ws, "latest_hand_rgb")


# ---- HTTPException helper --------------------------------------------------


def _http_kwargs(exc: RuleError) -> dict[str, Any]:
    """FastAPI's HTTPException flow cooperates with our error envelope middleware."""
    status = 409 if exc.code in ("TILE_MISMATCH", "INVALID_STATE", "PROPERTY_OWNED",
                                  "NOT_OWNER", "INSUFFICIENT_FUNDS",
                                  "JAIL_EXIT_UNAVAILABLE") else 400
    if exc.code == "NOT_FOUND":
        status = 404
    return {"status_code": status, "detail": {"code": exc.code, "message": str(exc), "details": exc.details}}
