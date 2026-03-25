"""Scheduling trigger implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from ha_autoupgrade.constants import DEFAULT_WEEKDAYS
from ha_autoupgrade.utils.cron import next_cron_occurrence
from ha_autoupgrade.utils.dates import add_seconds, deterministic_jitter, parse_hhmm, parse_weekday_time

_WEEKDAY_MAP = {day: index for index, day in enumerate(DEFAULT_WEEKDAYS)}


class Trigger(ABC):
    @abstractmethod
    def next_after(self, now: datetime, *, seed: str, jitter_seconds: int) -> datetime:
        raise NotImplementedError


class IntervalTrigger(Trigger):
    def __init__(self, minutes: int) -> None:
        self.minutes = minutes

    def next_after(self, now: datetime, *, seed: str, jitter_seconds: int) -> datetime:
        next_run = now + timedelta(minutes=self.minutes)
        return add_seconds(next_run, deterministic_jitter(jitter_seconds, seed))


class CronTrigger(Trigger):
    def __init__(self, expression: str) -> None:
        self.expression = expression

    def next_after(self, now: datetime, *, seed: str, jitter_seconds: int) -> datetime:
        next_run = next_cron_occurrence(self.expression, now)
        return add_seconds(next_run, deterministic_jitter(jitter_seconds, seed))


class WeekdayTimeTrigger(Trigger):
    def __init__(self, expression: str) -> None:
        self.weekday, self.at_time = parse_weekday_time(expression)

    def next_after(self, now: datetime, *, seed: str, jitter_seconds: int) -> datetime:
        days_ahead = (self.weekday - now.weekday()) % 7
        candidate = now.replace(
            hour=self.at_time.hour,
            minute=self.at_time.minute,
            second=0,
            microsecond=0,
        )
        if days_ahead == 0 and candidate <= now:
            days_ahead = 7
        candidate = candidate + timedelta(days=days_ahead)
        return add_seconds(candidate, deterministic_jitter(jitter_seconds, seed))


class WeekdaySetTimeTrigger(Trigger):
    def __init__(self, weekdays: tuple[str, ...] | list[str] | set[str], at_time: str) -> None:
        self.weekdays = {_WEEKDAY_MAP[weekday] for weekday in weekdays}
        self.at_time = parse_hhmm(at_time)

    def next_after(self, now: datetime, *, seed: str, jitter_seconds: int) -> datetime:
        for days_ahead in range(8):
            day = now + timedelta(days=days_ahead)
            candidate = day.replace(
                hour=self.at_time.hour,
                minute=self.at_time.minute,
                second=0,
                microsecond=0,
            )
            if candidate.weekday() not in self.weekdays:
                continue
            if candidate <= now:
                continue
            return add_seconds(candidate, deterministic_jitter(jitter_seconds, seed))
        raise ValueError("Weekday schedule did not resolve within one week")
