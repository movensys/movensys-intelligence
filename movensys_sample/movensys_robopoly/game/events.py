"""WS event bus (PRD §4.6).

Tiny in-process pub/sub. Each subscriber gets its own bounded queue so a
slow client backs up only its own stream. Publishers never await the
network — they call `publish_nowait` from inside FSM handlers.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

_QUEUE_MAXSIZE = 256


def make_envelope(event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "event_id": uuid.uuid4().hex,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "type": event_type,
        "payload": payload or {},
    }


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def publish_nowait(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        envelope = make_envelope(event_type, payload)
        for q in list(self._subscribers):
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                # Drop for slow subscribers rather than blocking the engine.
                pass
        return envelope

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
