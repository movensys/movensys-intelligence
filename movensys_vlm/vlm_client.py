import os
from typing import Optional

from openai import AsyncOpenAI

DEFAULT_SYSTEM_PROMPT = """You are a vision assistant for a simplified Monopoly game.

# The scene
- A **white rectangular board** sits on a black table, viewed from above.
- The board is divided by black grid lines into a **3 rows × 5 columns** layout, for **15 squares total**.
- **Player tokens** are small **colored cubes** placed inside individual squares. Tokens are noticeably smaller than a square and are usually rotated at some angle. Each token has a distinct color, except for WHITE.
- A separate **white die** with black pips may also be visible, but it sits **outside the board** (off to the side on the black table) and is NOT on a square. Ignore the die for token reporting.
- Ignore everything else: the gradient backdrop, the white pedestals, the lighting, any robotic arm, money, cards, or clutter.

# How to address squares
Use **(row, column)** coordinates, where:
- **row 0** = top row of the board (closest to the back wall in the image),
- **row 2** = bottom row (closest to the camera/front),
- **column 0** = leftmost column,
- **column 4** = rightmost column.

So the top-left square is `(0, 0)` and the bottom-right square is `(2, 4)`.

# What to report
For every image, output exactly in this form:

Tokens visible: <N>
- token 1: color=<color>, square=(<row>, <col>)
- token 2: color=<color>, square=(<row>, <col>)
...

Rules:
- Count **only cubes that are clearly inside a board square**. If a cube is on the black table outside the white board, do NOT list it.
- If you are unsure which of two adjacent squares a token sits in, list the most likely one and add `(uncertain)` after the coordinates.
- If you cannot identify a color confidently, write `color=unknown`.
- Be concise — no extra commentary."""

_system_prompt: str = DEFAULT_SYSTEM_PROMPT
_client: AsyncOpenAI | None = None


def get_system_prompt() -> str:
    return _system_prompt


def set_system_prompt(prompt: str) -> str:
    global _system_prompt
    _system_prompt = prompt
    return _system_prompt


def reset_system_prompt() -> str:
    global _system_prompt
    _system_prompt = DEFAULT_SYSTEM_PROMPT
    return _system_prompt


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        base_url = os.environ.get("VLM_BASE_URL", "http://192.168.0.73:8000/v1")
        api_key = os.environ.get("VLM_API_KEY", "none")
        timeout = float(os.environ.get("VLM_TIMEOUT", "60"))
        _client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    return _client


async def infer(
    image_b64: str,
    user_prompt: str = "Report the tokens on the board and the die value.",
    system_prompt: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    client = get_client()
    model = os.environ.get("VLM_MODEL", "google/gemma-4-E4B-it")
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt if system_prompt is not None else _system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                    {"type": "text", "text": user_prompt},
                ],
            },
        ],
    )
    return response.choices[0].message.content
