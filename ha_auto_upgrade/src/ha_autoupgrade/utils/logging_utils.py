"""Logging setup with optional JSON output and recent log buffering."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import logging
import sys
from typing import Any

from ha_autoupgrade.constants import RECENT_LOG_BUFFER_SIZE


class InMemoryLogHandler(logging.Handler):
    """Keeps the most recent log messages for the local dashboard."""

    def __init__(self) -> None:
        super().__init__()
        self.records: deque[dict[str, Any]] = deque(maxlen=RECENT_LOG_BUFFER_SIZE)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(
            {
                "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
                "level": record.levelname.lower(),
                "logger": record.name,
                "message": record.getMessage(),
            }
        )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self.records)[-limit:]


class JsonFormatter(logging.Formatter):
    """Render log entries as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


class TextFormatter(logging.Formatter):
    """Render human-readable log lines with a stable timestamp-first prefix."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging(level: str, json_logs: bool) -> InMemoryLogHandler:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level.upper())

    stream_handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        stream_handler.setFormatter(JsonFormatter())
    else:
        stream_handler.setFormatter(TextFormatter())

    memory_handler = InMemoryLogHandler()
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(memory_handler)
    logging.captureWarnings(True)
    return memory_handler
