"""Regenerate the printable whiteboard PNGs under boards/.

Three themes (Korea, USA, numbers) rendered as 1800x3000 portrait PNGs.
The board is drawn landscape (5x3 perimeter, matching board3_blank.svg)
and then rotated 90° counter-clockwise.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "boards"

CELL = 600
COLS, ROWS = 5, 3
W, H = COLS * CELL, ROWS * CELL  # 3000 x 1800 landscape

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Perimeter walked clockwise from START in the landscape coord frame.
PERIMETER = [
    (0, 0), (1, 0), (2, 0), (3, 0), (4, 0),
    (4, 1),
    (4, 2), (3, 2), (2, 2), (1, 2), (0, 2),
    (0, 1),
]

KOREA = ["START", "Incheon", "Suwon", "Daejeon", "Jeonju",
         "Gwangju",
         "Busan", "Ulsan", "Daegu", "Gyeongju", "Gangneung",
         "Chuncheon"]

USA = ["START", "New York", "Boston", "Philadelphia", "Washington",
       "Atlanta",
       "Miami", "Houston", "Dallas", "Denver", "Los Angeles",
       "Chicago"]

NUMBERS = ["START"] + [str(i) for i in range(1, 12)]

LINE_COLOR = (17, 17, 17)
TEXT_COLOR = (17, 17, 17)
BG = (255, 255, 255)
INNER_BG = (250, 250, 250)
LINE_W = 14
OUTER_LINE_W = LINE_W + 6


def fit_font(text: str, max_width: int, base_size: int) -> ImageFont.FreeTypeFont:
    size = base_size
    while size > 30:
        font = ImageFont.truetype(FONT_PATH, size)
        bbox = font.getbbox(text)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 6
    return ImageFont.truetype(FONT_PATH, size)


VPAD = 40  # padding from cell edge for "up"/"down" alignment


def render(
    labels: list[str],
    base_font_size: int,
    out_path: Path,
    align: str = "middle",
    rotate: bool = True,
) -> None:
    assert len(labels) == 12, "expected 12 perimeter labels"
    assert align in ("up", "middle", "down")
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    inner = (CELL, CELL, 4 * CELL, 2 * CELL)
    draw.rectangle(inner, fill=INNER_BG)

    for (c, r) in PERIMETER:
        x0, y0 = c * CELL, r * CELL
        draw.rectangle((x0, y0, x0 + CELL, y0 + CELL),
                       outline=LINE_COLOR, width=LINE_W)

    draw.rectangle(inner, outline=LINE_COLOR, width=LINE_W)
    draw.rectangle((0, 0, W - 1, H - 1),
                   outline=LINE_COLOR, width=OUTER_LINE_W)

    for (c, r), label in zip(PERIMETER, labels):
        x0, y0 = c * CELL, r * CELL
        cx = x0 + CELL // 2
        font = fit_font(label, CELL - 80, base_font_size)
        bb = draw.textbbox((0, 0), label, font=font)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        if align == "up":
            ty = y0 + VPAD - bb[1]
        elif align == "down":
            ty = y0 + CELL - VPAD - bh - bb[1]
        else:
            ty = y0 + CELL // 2 - bh // 2 - bb[1]
        draw.text((cx - bw // 2 - bb[0], ty),
                  label, font=font, fill=TEXT_COLOR)

    out = img.rotate(90, expand=True) if rotate else img
    out.save(out_path, format="PNG", optimize=True)
    print(f"wrote {out_path} ({out.size[0]}x{out.size[1]})")


def main() -> None:
    themes = [
        ("korea", KOREA, 150),
        ("usa", USA, 130),
        ("w_number", NUMBERS, 280),
    ]
    for name, labels, size in themes:
        for align in ("up", "middle", "down"):
            render(
                labels,
                size,
                OUT_DIR / f"whiteboard_{name}_{align}.png",
                align=align,
                rotate=False,
            )


if __name__ == "__main__":
    main()
