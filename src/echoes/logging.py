"""Structured standard-library logging for Project Echoes."""

from __future__ import annotations

import json
import logging as stdlib_logging
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(stdlib_logging.Formatter):
    """Render each log record as one machine-readable JSON object."""

    def format(self, record: stdlib_logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(level: str = "INFO") -> stdlib_logging.Logger:
    """Configure the root logger once and return the project logger."""
    root = stdlib_logging.getLogger()
    root.handlers.clear()
    handler = stdlib_logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    return stdlib_logging.getLogger("echoes")
