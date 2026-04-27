import os
from typing import Optional

from openai import AsyncOpenAI

DEFAULT_SYSTEM_PROMPT = """You are a vision assistant for a city-themed board game.

# The board
- A rectangular board viewed from above, with a 3-row × 5-column grid of named squares.
- Every cell has a visible city name written inside it.
- The center cell (row 2, col 2-4) is a large empty area — it contains no city name and no tokens.
- Square names by position (row, col), 0-indexed top-left:

  Row 0 (top):    (0,0)=START, (0,1)=New York, (0,2)=Boston, (0,3)=Philadelphia, (0,4)=Washington
  Row 1 (middle): (1,0)=Chicago,                                                   (1,4)=Atlanta
  Row 2 (bottom): (2,0)=Los Angeles, (2,1)=Denver, (2,2)=Dallas, (2,3)=Houston, (2,4)=Miami

- Player tokens are small colored cubes or pieces placed on squares.
- Ignore anything outside the board.

# How to locate a token
1. Find the token's center position in the image.
2. Determine which named cell that center falls inside using the grid lines.
3. Report the square by reading the city name text visible inside that cell.
4. Do NOT count grid positions — read the label directly.

# What to report
Tokens visible: <N>
- token 1: color=<color>, square=<square name>
- token 2: color=<color>, square=<square name>
...

- Omit tokens in the center empty area or outside the board.
- If a token straddles a grid line, pick the cell with the majority of the token and add `(uncertain)`.
- If color is unclear: `color=unknown`.
- No extra commentary."""

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
