"""Scheduling trigger implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from croniter import croniter

from ha_autoupgrade.utils.dates import add_seconds, deterministic_jitter, parse_weekday_time


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
        next_run = croniter(self.expression, now).get_next(datetime)
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
