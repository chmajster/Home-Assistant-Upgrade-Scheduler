"""Data models used by the add-on."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


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
