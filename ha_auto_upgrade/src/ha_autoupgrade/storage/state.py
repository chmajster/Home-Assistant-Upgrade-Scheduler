"""Persistent state storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ha_autoupgrade.constants import STATE_FILE, STATE_SCHEMA_VERSION
from ha_autoupgrade.models import RunSummary, UpdateCandidate
from ha_autoupgrade.utils.dates import utc_now


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "last_check": None,
        "last_run": None,
        "last_backup": None,
        "pending_updates": [],
        "next_check": None,
        "next_install": None,
        "running_job": None,
        "failure_count": 0,
        "safe_mode_until": None,
        "safe_mode_reason": "",
        "cooldown_until": None,
        "retry_queue": [],
        "last_self_test": None,
        "schedule_signature": "",
    }


class StateStore:
    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.write(_default_state())

    def read(self) -> dict[str, Any]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != STATE_SCHEMA_VERSION:
            payload = self._migrate(payload)
        return payload

    def write(self, payload: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.path)

    def update(self, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        state = self.read()
        updater(state)
        self.write(state)
        return state

    def _migrate(self, payload: dict[str, Any]) -> dict[str, Any]:
        migrated = _default_state()
        migrated.update(payload)
        migrated["schema_version"] = STATE_SCHEMA_VERSION
        self.write(migrated)
        return migrated

    def mark_interrupted_if_running(self) -> None:
        def _update(state: dict[str, Any]) -> None:
            running_job = state.get("running_job")
            if not running_job:
                return
            state["last_run"] = {
                "status": "interrupted",
                "trigger": running_job.get("trigger"),
                "mode": running_job.get("mode"),
                "started_at": running_job.get("started_at"),
                "completed_at": utc_now().isoformat(),
                "results": [],
                "skipped_reasons": ["Previous run was interrupted by restart"],
                "backup_id": running_job.get("backup_id"),
                "detected_updates": running_job.get("pending_items", []),
            }
            state["retry_queue"] = running_job.get("pending_items", [])
            state["running_job"] = None

        self.update(_update)

    def set_next_runs(self, next_check: str | None, next_install: str | None) -> None:
        self.update(
            lambda state: state.update(
                {
                    "next_check": next_check,
                    "next_install": next_install,
                }
            )
        )

    def set_schedule_signature(self, signature: str) -> None:
        self.update(lambda state: state.update({"schedule_signature": signature}))

    def record_check(
        self,
        *,
        candidates: list[UpdateCandidate],
        skipped: list[dict[str, Any]],
        next_check: str | None,
        next_install: str | None,
    ) -> None:
        self.update(
            lambda state: state.update(
                {
                    "last_check": {
                        "checked_at": utc_now().isoformat(),
                        "found": [candidate.to_dict() for candidate in candidates],
                        "skipped": skipped,
                    },
                    "pending_updates": [candidate.to_dict() for candidate in candidates],
                    "next_check": next_check,
                    "next_install": next_install,
                }
            )
        )

    def start_job(self, *, mode: str, trigger: str, pending_items: list[dict[str, Any]]) -> None:
        self.update(
            lambda state: state.update(
                {
                    "running_job": {
                        "mode": mode,
                        "trigger": trigger,
                        "started_at": utc_now().isoformat(),
                        "pending_items": pending_items,
                        "backup_id": None,
                    }
                }
            )
        )

    def set_running_backup_id(self, backup_id: str) -> None:
        def _update(state: dict[str, Any]) -> None:
            if state.get("running_job"):
                state["running_job"]["backup_id"] = backup_id

        self.update(_update)

    def finish_job(self, summary: RunSummary) -> None:
        failed_keys = {
            result.slug or result.component_type
            for result in summary.results
            if result.result == "failed"
        }
        pending_updates = []
        if failed_keys:
            pending_updates = [
                item.to_dict()
                for item in summary.detected_updates
                if (item.slug or item.component_type) in failed_keys
            ]
        self.update(
            lambda state: state.update(
                {
                    "last_run": summary.to_dict(),
                    "running_job": None,
                    "pending_updates": pending_updates,
                    "last_backup": summary.backup_id or state.get("last_backup"),
                }
            )
        )

    def mark_backup(self, backup_id: str) -> None:
        self.update(lambda state: state.update({"last_backup": backup_id}))

    def set_failure_mode(
        self,
        *,
        failure_count: int,
        cooldown_until: str | None,
        safe_mode_until: str | None,
        safe_mode_reason: str,
    ) -> None:
        self.update(
            lambda state: state.update(
                {
                    "failure_count": failure_count,
                    "cooldown_until": cooldown_until,
                    "safe_mode_until": safe_mode_until,
                    "safe_mode_reason": safe_mode_reason,
                }
            )
        )

    def clear_failure_mode(self) -> None:
        self.update(
            lambda state: state.update(
                {
                    "failure_count": 0,
                    "cooldown_until": None,
                    "safe_mode_until": None,
                    "safe_mode_reason": "",
                }
            )
        )

    def queue_retry(self, items: list[dict[str, Any]]) -> None:
        self.update(lambda state: state.update({"retry_queue": items}))

    def clear_retry_queue(self) -> None:
        self.update(lambda state: state.update({"retry_queue": []}))

    def clear_stuck_state(self) -> None:
        self.update(
            lambda state: state.update(
                {
                    "running_job": None,
                    "retry_queue": [],
                    "cooldown_until": None,
                    "safe_mode_until": None,
                    "safe_mode_reason": "",
                }
            )
        )

    def mark_self_test(self, payload: dict[str, Any]) -> None:
        self.update(lambda state: state.update({"last_self_test": payload}))
