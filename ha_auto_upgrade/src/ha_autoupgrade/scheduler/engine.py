"""Internal scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.constants import DEFAULT_WEEKDAYS
from ha_autoupgrade.scheduler.triggers import (
    CronTrigger,
    IntervalTrigger,
    MonthlyDayTimeTrigger,
    OneTimeTrigger,
    Trigger,
    WeekdaySetTimeTrigger,
    WeekdayTimeTrigger,
)
from ha_autoupgrade.utils.dates import parse_iso_datetime, utc_now


@dataclass(slots=True)
class ScheduleSnapshot:
    next_check: datetime | None
    next_install: datetime | None


class SchedulerEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _trigger_for(self, mode: str) -> Trigger:
        if mode == "check":
            if self.config.schedule_check_cron:
                return CronTrigger(self.config.schedule_check_cron)
            if self.config.schedule_check_weekday_time:
                return WeekdayTimeTrigger(self.config.schedule_check_weekday_time)
            return IntervalTrigger(self.config.schedule_check_interval_minutes)

        if self.config.schedule_install_frequency == "once" and self.config.schedule_install_once_at:
            return OneTimeTrigger(self.config.schedule_install_once_at)
        if self.config.schedule_install_frequency == "monthly":
            return MonthlyDayTimeTrigger(
                self.config.schedule_install_monthday,
                self.config.install_hour,
            )
        if self.config.schedule_install_frequency == "daily":
            return WeekdaySetTimeTrigger(DEFAULT_WEEKDAYS, self.config.install_hour)
        if self.config.schedule_install_frequency == "weekly":
            return WeekdaySetTimeTrigger(self.config.install_days, self.config.install_hour)
        if self.config.schedule_install_cron:
            return CronTrigger(self.config.schedule_install_cron)
        if self.config.install_days and self.config.install_hour:
            return WeekdaySetTimeTrigger(self.config.install_days, self.config.install_hour)
        if self.config.schedule_install_weekday_time:
            return WeekdayTimeTrigger(self.config.schedule_install_weekday_time)
        return IntervalTrigger(self.config.schedule_install_interval_minutes)

    def compute_next(self, mode: str, now: datetime | None = None) -> datetime:
        current = now or utc_now()
        trigger = self._trigger_for(mode)
        seed = f"{mode}:{current.date().isoformat()}:{self.config.staged_rollout_seed}"
        return trigger.next_after(
            current,
            seed=seed,
            jitter_seconds=self.config.schedule_jitter_seconds,
        )

    def ensure_schedule(self, state: dict[str, object], now: datetime | None = None) -> ScheduleSnapshot:
        current = now or utc_now()
        next_check = parse_iso_datetime(state.get("next_check")) if state.get("next_check") else None
        next_install = parse_iso_datetime(state.get("next_install")) if state.get("next_install") else None
        if next_check is None:
            next_check = self.compute_next("check", current)
        if next_install is None:
            next_install = self.compute_next("install", current)
        return ScheduleSnapshot(next_check=next_check, next_install=next_install)

    def due_actions(self, state: dict[str, object], now: datetime | None = None) -> list[str]:
        current = now or utc_now()
        schedule = self.ensure_schedule(state, current)
        due: list[str] = []
        if schedule.next_check and schedule.next_check <= current:
            due.append("check")
        if schedule.next_install and schedule.next_install <= current:
            due.append("install")
        return due
