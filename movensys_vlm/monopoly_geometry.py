"""Map a piece world (x, y) to a structural board cell index.

Returns only (row, col) and a status flag — the actual cell label (city
name) is intentionally NOT in this module. The VLM reads the label from
the camera image so the system generalizes to any printed board.

Local frame (board origin at center, derived from /board Pose):
    +X -> long axis, image left to right (col 0 -> col 4)
    +Y -> short axis, image bottom to top (row 2 -> row 0)

Board physical extents come from the placement bounds in
``randomize_tokens_loop.py`` (GRID_X span = 0.23 m, GRID_Y span = 0.36 m).
Adjust the constants if the physical board changes.
"""
import math
from typing import Optional, Tuple

BOARD_LEN_X = 0.36
BOARD_LEN_Y = 0.23
N_COLS = 5
N_ROWS = 3
CELL_X = BOARD_LEN_X / N_COLS
CELL_Y = BOARD_LEN_Y / N_ROWS

# Structurally empty interior of the middle row (no printed label).
CENTER_EMPTY = {(1, 1), (1, 2), (1, 3)}


def yaw_from_quat(qx: float, qy: float, qz: float, qw: float) -> float:
    return math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))


def world_to_local(piece_xy: Tuple[float, float],
                   board_xy: Tuple[float, float],
                   board_yaw: float) -> Tuple[float, float]:
    dx = piece_xy[0] - board_xy[0]
    dy = piece_xy[1] - board_xy[1]
    c, s = math.cos(-board_yaw), math.sin(-board_yaw)
    return c * dx - s * dy, s * dx + c * dy


def local_to_cell(lx: float, ly: float) -> Optional[Tuple[int, int]]:
    half_x = BOARD_LEN_X / 2.0
    half_y = BOARD_LEN_Y / 2.0
    if not (-half_x <= lx <= half_x and -half_y <= ly <= half_y):
        return None
    col = min(N_COLS - 1, max(0, int((lx + half_x) / CELL_X)))
    row = min(N_ROWS - 1, max(0, int((half_y - ly) / CELL_Y)))
    return row, col


def classify_piece(piece_xy: Tuple[float, float],
                   board_xy: Tuple[float, float],
                   board_quat: Tuple[float, float, float, float]) -> dict:
    """Return cell index + status. The label itself is left for the VLM."""
    yaw = yaw_from_quat(*board_quat)
    lx, ly = world_to_local(piece_xy, board_xy, yaw)
    cell = local_to_cell(lx, ly)
    if cell is None:
        return {"status": "off_board", "row": None, "col": None,
                "local_x": lx, "local_y": ly}
    row, col = cell
    status = "center_empty" if cell in CENTER_EMPTY else "on_board"
    return {"status": status, "row": row, "col": col,
            "local_x": lx, "local_y": ly}
