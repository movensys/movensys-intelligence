import os
from typing import Optional

from openai import AsyncOpenAI

DEFAULT_SYSTEM_PROMPT = """You are a vision assistant for a board game played on a printed grid.

The user will provide:
- A top-down camera image of the board.
- For each token: a sensor-derived cell index `(row, col)` plus a status of
  `on_board`, `off_board`, or `center_empty`.

The board has 3 rows and 5 columns. In the camera image:
- row=0 is the top edge of the board, row=2 is the bottom edge.
- col=0 is the left edge, col=4 is the right edge.

Each on-board cell has a label (a place/city name) printed inside it.
The label set is NOT given to you in advance — read it directly from the
image. Boards may change between runs.

# Your job
For every token with status `on_board`:
1. Locate the cell at the given (row, col) in the image.
2. Read the label printed inside that cell.
3. Identify the token's color.

Skip tokens whose status is `off_board` or `center_empty`.

# Output format
Tokens visible: <N>
- token 1: color=<color>, square=<label read from the image>
- token 2: color=<color>, square=<label read from the image>
...

Rules:
- Use a simple color name (red, blue, green, yellow, white, black, pink, orange, purple, brown, gray); use `unknown` if unclear.
- If the cell label is unreadable, write `square=unreadable`.
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
        base_url = os.environ.get("VLLM_BASE_URL", "http://localhost:9000/v1")
        api_key = os.environ.get("HF_TOKEN") or "EMPTY"
        timeout = float(os.environ.get("VLM_TIMEOUT") or 60)
        _client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    return _client


async def infer(
    image_b64: Optional[str] = None,
    user_prompt: str = "Report the tokens on the board and the die value.",
    system_prompt: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    client = get_client()
    model = os.environ.get("VLM_MODEL_NAME")
    user_content: list = []
    if image_b64:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        })
    user_content.append({"type": "text", "text": user_prompt})
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt if system_prompt is not None else _system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content
