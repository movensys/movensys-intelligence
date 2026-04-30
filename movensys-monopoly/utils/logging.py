"""Structured JSON logger with request-scoped event_id (PRD §11.4)."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from typing import Any

_event_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("event_id", default=None)


def new_event_id() -> str:
    eid = uuid.uuid4().hex
    _event_id.set(eid)
    return eid


def current_event_id() -> str | None:
    return _event_id.get()


def bind_event_id(eid: str) -> None:
    _event_id.set(eid)


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        eid = current_event_id()
        if eid:
            payload["event_id"] = eid
        for key, value in record.__dict__.items():
            if key in ("args", "msg", "levelname", "name", "created", "msecs",
                      "levelno", "pathname", "filename", "module", "exc_info",
                      "exc_text", "stack_info", "lineno", "funcName", "thread",
                      "threadName", "processName", "process", "relativeCreated"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure() -> None:
    """Replace root handlers with a single JSON stream handler."""
    level_name = os.environ.get("MONOPOLY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    root.addHandler(handler)
    root.setLevel(level)
