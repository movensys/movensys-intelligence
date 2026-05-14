import logging
import os
import time
import uuid
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_qdrant_client: httpx.AsyncClient | None = None
_embed_client: httpx.AsyncClient | None = None
_collection_ready: bool = False


def is_enabled() -> bool:
    return os.environ.get("MEMORY_ENABLED", "false").lower() in ("1", "true", "yes")


def _collection() -> str:
    return os.environ.get("MEMORY_COLLECTION", "vlm_memory")


def _vector_size() -> int:
    return int(os.environ.get("MEMORY_VECTOR_SIZE", "384"))


def _top_k() -> int:
    return int(os.environ.get("MEMORY_TOP_K", "3"))


def _timeout() -> float:
    return float(os.environ.get("MEMORY_TIMEOUT", "10"))


def _qdrant() -> httpx.AsyncClient:
    global _qdrant_client
    if _qdrant_client is None:
        base = os.environ.get("MEMORY_QDRANT_URL", "http://localhost:6333")
        _qdrant_client = httpx.AsyncClient(base_url=base, timeout=_timeout())
    return _qdrant_client


def _embed() -> httpx.AsyncClient:
    global _embed_client
    if _embed_client is None:
        base = os.environ.get("MEMORY_EMBED_BASE_URL", "http://localhost:9020")
        _embed_client = httpx.AsyncClient(base_url=base, timeout=_timeout())
    return _embed_client


async def _ensure_collection() -> None:
    global _collection_ready
    if _collection_ready:
        return
    name = _collection()
    q = _qdrant()
    r = await q.get(f"/collections/{name}")
    if r.status_code == 200:
        _collection_ready = True
        return
    r = await q.put(
        f"/collections/{name}",
        json={"vectors": {"size": _vector_size(), "distance": "Cosine"}},
    )
    r.raise_for_status()
    _collection_ready = True


async def embed_text(text: str) -> list[float]:
    r = await _embed().post("/embed", json={"inputs": text})
    r.raise_for_status()
    data = r.json()
    # TEI returns either [[...]] for single input or [[...], [...]] for batch.
    return data[0] if isinstance(data[0], list) else data


async def store(text: str, metadata: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Embed `text` and upsert into Qdrant. Returns the point id, or None on failure."""
    if not is_enabled() or not text:
        return None
    try:
        await _ensure_collection()
        vector = await embed_text(text)
        point_id = str(uuid.uuid4())
        payload = {"text": text, "ts": time.time()}
        if metadata:
            payload.update(metadata)
        r = await _qdrant().put(
            f"/collections/{_collection()}/points?wait=true",
            json={"points": [{"id": point_id, "vector": vector, "payload": payload}]},
        )
        r.raise_for_status()
        return point_id
    except Exception as exc:
        logger.warning("memory.store failed: %s", exc)
        return None


async def recall(query: str, top_k: Optional[int] = None) -> list[dict[str, Any]]:
    """Return up to `top_k` payloads most similar to `query`. Empty list on failure."""
    if not is_enabled() or not query:
        return []
    try:
        await _ensure_collection()
        vector = await embed_text(query)
        r = await _qdrant().post(
            f"/collections/{_collection()}/points/search",
            json={
                "vector": vector,
                "limit": top_k if top_k is not None else _top_k(),
                "with_payload": True,
            },
        )
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as exc:
        logger.warning("memory.recall failed: %s", exc)
        return []


def format_recall(hits: list[dict[str, Any]]) -> str:
    """Render recall results as a compact bullet list for prompt injection."""
    if not hits:
        return ""
    lines = []
    for h in hits:
        payload = h.get("payload") or {}
        text = payload.get("text", "").strip()
        if not text:
            continue
        score = h.get("score")
        lines.append(f"- (score={score:.2f}) {text}" if score is not None else f"- {text}")
    if not lines:
        return ""
    return "Relevant past observations:\n" + "\n".join(lines)
