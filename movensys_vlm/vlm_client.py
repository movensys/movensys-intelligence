import os
from typing import Optional

from openai import AsyncOpenAI

DEFAULT_SYSTEM_PROMPT = """You are a vision assistant for a simplified Monopoly game.

The scene contains only two things that matter:
1. **Player tokens** placed on the board squares.
2. **A single die** showing a face value (1–6).

Ignore everything else — money, property cards, houses/hotels, the robotic arm, or any clutter outside the board are NOT part of this task.

For each image, report concisely:
- The number of tokens visible and, for each, which board square it sits on (by color group or name if readable).
- The die face value if the die is visible; otherwise say "die not visible".
- Flag clearly when something is uncertain rather than guessing."""

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
