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


def test_monthly_schedule_resolves_next_target() -> None:
    config = AppConfig.from_dict(
        {
            "install_days": "mon,tue,wed,thu,fri,sat,sun",
            "install_hour": "04:30",
            "schedule_install_frequency": "monthly",
            "schedule_install_monthday": 1,
            "schedule_jitter_seconds": 0,
        }
    )
    scheduler = SchedulerEngine(config)
    now = datetime(2026, 3, 25, 10, 0, tzinfo=UTC)

    next_run = scheduler.compute_next("install", now)

    assert next_run == datetime(2026, 4, 1, 4, 30, tzinfo=UTC)


def test_one_time_schedule_resolves_future_target() -> None:
    config = AppConfig.from_dict(
        {
            "install_days": "fri",
            "install_hour": "04:30",
            "schedule_install_frequency": "once",
            "schedule_install_once_at": "2026-03-26T18:45:00+00:00",
            "schedule_jitter_seconds": 0,
        }
    )
    scheduler = SchedulerEngine(config)
    now = datetime(2026, 3, 25, 10, 0, tzinfo=UTC)

    next_run = scheduler.compute_next("install", now)

    assert next_run == datetime(2026, 3, 26, 18, 45, tzinfo=UTC)


def test_legacy_wildcard_schedule_values_fall_back_to_defaults() -> None:
    config = AppConfig.from_dict(
        {
            "install_days": "*",
            "install_hour": "*",
        }
    )

    assert config.install_days == ("sun",)
    assert config.install_hour == "03:00"
