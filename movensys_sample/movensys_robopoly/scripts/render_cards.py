#!/usr/bin/env python3
"""
Render property/railroad/utility SVG cards from a board JSON definition.

Usage:
    python3 scripts/render_cards.py static/assets/boards/board2.json \
        --out static/assets/property_cards/board2/

Reads board JSON (§4.4 of PRD.md), stamps templates, writes one SVG per tile.
Templates live next to this script's output dir:
    static/assets/property_cards/{template,_railroad_template,_utility_template}.svg
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "static" / "assets" / "property_cards"
SLUG_RE = re.compile(r"[^a-z0-9]+")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_comments(svg: str) -> str:
    """Drop template doc comments so placeholder text isn't accidentally rendered."""
    return COMMENT_RE.sub("", svg)


def slug(name: str) -> str:
    return SLUG_RE.sub("_", name.lower()).strip("_")


def fmt(n: int) -> str:
    return f"${n}"


def render_property(tile: dict, color_hex: str, tmpl: str) -> str:
    r = tile["rent_table"]
    replacements = {
        "NAME": tile["name"],
        "COLOR_HEX": color_hex,
        "PRICE_BUY": fmt(tile["price_buy"]),
        "RENT_BASE": fmt(r[0]),
        "RENT_H1": fmt(r[1]),
        "RENT_H2": fmt(r[2]),
        "RENT_H3": fmt(r[3]),
        "RENT_H4": fmt(r[4]),
        "RENT_HOTEL": fmt(r[5]),
        "PRICE_HOUSE": fmt(tile["price_building"]),
        "PRICE_HOTEL": f'{fmt(tile["price_building"])} + 4 houses',
    }
    out = tmpl
    for k, v in replacements.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def render_railroad(tile: dict, tmpl: str) -> str:
    return tmpl.replace("{{NAME}}", tile["name"])


def render_utility(tile: dict, tmpl: str) -> str:
    return tmpl.replace("{{NAME}}", tile["name"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("board_json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    board = json.loads(Path(args.board_json).read_text())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    prop_tmpl = strip_comments((ASSETS / "template.svg").read_text())
    rail_tmpl = strip_comments((ASSETS / "_railroad_template.svg").read_text())
    util_tmpl = strip_comments((ASSETS / "_utility_template.svg").read_text())
    colors = board.get("color_group_hex", {})

    count = 0
    for tile in board["tiles"]:
        kind = tile["kind"]
        name = tile["name"]
        if kind == "property":
            color = colors.get(tile.get("color_group"), "#888")
            svg = render_property(tile, color, prop_tmpl)
        elif kind == "railroad":
            svg = render_railroad(tile, rail_tmpl)
        elif kind == "utility":
            svg = render_utility(tile, util_tmpl)
        else:
            continue
        (out_dir / f"{slug(name)}.svg").write_text(svg)
        count += 1

    print(f"wrote {count} card SVGs to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
