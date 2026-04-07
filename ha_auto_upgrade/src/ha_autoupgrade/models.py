"""Data models used by the add-on."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ha_autoupgrade.constants import DEFAULT_WEEKDAYS


@dataclass(slots=True)
class ActionCall:
    service: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Decision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SystemSnapshot:
    free_disk_mb: int
    load_1m: float | None
    free_memory_mb: int | None
    network_ok: bool
    api_ok: bool
    ha_state: str
    supervisor_state: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UpdateCandidate:
    component_type: str
    name: str
    current_version: str
    target_version: str
    slug: str | None = None
    security: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        return self.slug or self.component_type

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UpdatePlan:
    items: list[UpdateCandidate]
    skipped: list[dict[str, Any]]
    generated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "skipped": self.skipped,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass(slots=True)
class UpdateResult:
    component_type: str
    name: str
    previous_version: str
    target_version: str
    result: str
    duration_seconds: float
    slug: str | None = None
    reason: str = ""
    backup_id: str | None = None
    job_id: str | None = None
    health_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunSummary:
    trigger: str
    mode: str
    started_at: datetime
    completed_at: datetime
    status: str
    results: list[UpdateResult] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)
    backup_id: str | None = None
    detected_updates: list[UpdateCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "status": self.status,
            "results": [result.to_dict() for result in self.results],
            "skipped_reasons": self.skipped_reasons,
            "backup_id": self.backup_id,
            "detected_updates": [item.to_dict() for item in self.detected_updates],
        }


@dataclass(slots=True)
class SelfTestResult:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TASK_TYPE_ACTIONS: dict[str, str] = {
    "auto_update": "install",
    "auto_check_update": "check",
}


TASK_TYPE_NAMES: dict[str, str] = {
    "auto_update": "Auto Update",
    "auto_check_update": "Auto Check Update",
}


TASK_TYPE_DESCRIPTIONS: dict[str, str] = {
    "auto_update": "Automatyczna instalacja aktualizacji",
    "auto_check_update": "Automatyczne sprawdzanie aktualizacji",
}


@dataclass(slots=True)
class ScheduleTask:
    task_id: str
    task_type: str
    weekdays: tuple[str, ...]
    hour: int
    minute: int
    enabled: bool
    next_run: str | None = None
    category: str = "System"
    owner: str = "HA AutoUpgrade"
    created_at: str | None = None
    updated_at: str | None = None

    def validate(self) -> None:
        if self.task_type not in TASK_TYPE_ACTIONS:
            raise ValueError(f"Unsupported task type: {self.task_type}")
        if not self.weekdays:
            raise ValueError("Task weekdays cannot be empty")
        if any(day not in DEFAULT_WEEKDAYS for day in self.weekdays):
            raise ValueError("Task weekdays contain unsupported values")
        if self.hour < 0 or self.hour > 23:
            raise ValueError("Task hour must be between 0 and 23")
        if self.minute < 0 or self.minute > 59:
            raise ValueError("Task minute must be between 0 and 59")

    @property
    def action(self) -> str:
        return TASK_TYPE_ACTIONS[self.task_type]

    @property
    def name(self) -> str:
        return TASK_TYPE_NAMES[self.task_type]

    @property
    def description(self) -> str:
        return TASK_TYPE_DESCRIPTIONS[self.task_type]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.task_id,
            "task_type": self.task_type,
            "weekdays": list(self.weekdays),
            "hour": self.hour,
            "minute": self.minute,
            "enabled": self.enabled,
            "next_run": self.next_run,
            "category": self.category,
            "owner": self.owner,
            "name": self.name,
            "action": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScheduleTask":
        task = cls(
            task_id=str(payload.get("id", "")),
            task_type=str(payload.get("task_type", "")).strip().lower(),
            weekdays=tuple(str(day).strip().lower() for day in payload.get("weekdays", [])),
            hour=int(payload.get("hour", 0)),
            minute=int(payload.get("minute", 0)),
            enabled=bool(payload.get("enabled", True)),
            next_run=str(payload.get("next_run")) if payload.get("next_run") else None,
            category=str(payload.get("category") or "System"),
            owner=str(payload.get("owner") or "HA AutoUpgrade"),
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            updated_at=str(payload.get("updated_at")) if payload.get("updated_at") else None,
        )
        task.validate()
        return task
