from __future__ import annotations

from datetime import UTC, datetime

from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.scheduler.engine import SchedulerEngine


def test_interval_schedule_computes_future_run() -> None:
    config = AppConfig.from_dict(
        {
            "schedule_check_interval_minutes": 30,
            "schedule_jitter_seconds": 0,
        }
    )
    scheduler = SchedulerEngine(config)
    now = datetime(2026, 3, 25, 10, 0, tzinfo=UTC)

    next_run = scheduler.compute_next("check", now)

    assert next_run == datetime(2026, 3, 25, 10, 30, tzinfo=UTC)


def test_weekday_schedule_resolves_next_target() -> None:
    config = AppConfig.from_dict(
        {
            "install_days": "fri,sun",
            "install_hour": "03:00",
            "schedule_jitter_seconds": 0,
        }
    )
    scheduler = SchedulerEngine(config)
    now = datetime(2026, 3, 25, 10, 0, tzinfo=UTC)

    next_run = scheduler.compute_next("install", now)

    assert next_run == datetime(2026, 3, 27, 3, 0, tzinfo=UTC)
