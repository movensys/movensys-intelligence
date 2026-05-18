import asyncio
import os
from typing import Optional

from openai import AsyncOpenAI

import memory_client

DEFAULT_SYSTEM_PROMPT = """You are a vision assistant for a board game played on a printed grid."""

DEFAULT_CLIENT = "default"
_system_prompts: dict[str, str] = {DEFAULT_CLIENT: DEFAULT_SYSTEM_PROMPT}
_client: AsyncOpenAI | None = None


def _client_key(client: Optional[str]) -> str:
    return (client or DEFAULT_CLIENT).strip() or DEFAULT_CLIENT


def get_system_prompt(client: Optional[str] = None) -> str:
    return _system_prompts.get(_client_key(client), DEFAULT_SYSTEM_PROMPT)


def set_system_prompt(prompt: str, client: Optional[str] = None) -> str:
    key = _client_key(client)
    _system_prompts[key] = prompt
    return _system_prompts[key]


def reset_system_prompt(client: Optional[str] = None) -> str:
    key = _client_key(client)
    _system_prompts[key] = DEFAULT_SYSTEM_PROMPT
    return _system_prompts[key]


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        base_url = os.environ.get("VLM_BASE_URL", "http://localhost:9000/v1")
        api_key = os.environ.get("HF_TOKEN") or "EMPTY"
        timeout = float(os.environ.get("VLM_TIMEOUT") or 60)
        _client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    return _client


async def infer(
    image_b64: Optional[str] = None,
    user_prompt: str = "Report the tokens on the board and the die value.",
    system_prompt: Optional[str] = None,
    max_tokens: int = 128,
    temperature: float = 0.2,
    client_id: Optional[str] = None,
) -> str:
    client = get_client()
    model = os.environ.get("VLM_MODEL_NAME")

    base_system = system_prompt if system_prompt is not None else get_system_prompt(client_id)
    # Memory belongs to conversation, not perception: skip recall/store on
    # camera-grounded frames so per-frame polling can't pollute the store
    # with stale token reports.
    use_memory = image_b64 is None
    memory_block = (
        memory_client.format_recall(await memory_client.recall(user_prompt))
        if use_memory else ""
    )
    effective_system = f"{base_system}\n\n{memory_block}" if memory_block else base_system

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
            {"role": "system", "content": effective_system},
            {"role": "user", "content": user_content},
        ],
    )
    answer = response.choices[0].message.content or ""
    if use_memory:
        asyncio.create_task(memory_client.store(
            f"Q: {user_prompt}\nA: {answer}",
            metadata={"model": model},
        ))
    return answer
