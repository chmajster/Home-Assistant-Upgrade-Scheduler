"""Append-only audit history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ha_autoupgrade.constants import HISTORY_FILE, HISTORY_RETENTION


class HistoryStore:
    def __init__(self, path: Path = HISTORY_FILE) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        self._trim()

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:]]

    def _trim(self) -> None:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= HISTORY_RETENTION:
            return
        self.path.write_text("\n".join(lines[-HISTORY_RETENTION:]) + "\n", encoding="utf-8")
