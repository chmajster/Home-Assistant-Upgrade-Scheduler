"""Scheduling trigger implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
import calendar
from datetime import datetime, timedelta

from ha_autoupgrade.constants import DEFAULT_WEEKDAYS
from ha_autoupgrade.utils.cron import next_cron_occurrence
from ha_autoupgrade.utils.dates import (
    add_seconds,
    deterministic_jitter,
    parse_hhmm,
    parse_iso_datetime,
    parse_weekday_time,
)

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


class OneTimeTrigger(Trigger):
    def __init__(self, scheduled_for: str) -> None:
        parsed = parse_iso_datetime(scheduled_for)
        if parsed is None:
            raise ValueError("One-time schedule requires a valid ISO datetime")
        self.scheduled_for = parsed

    def next_after(self, now: datetime, *, seed: str, jitter_seconds: int) -> datetime:
        if self.scheduled_for > now:
            return self.scheduled_for
        return now + timedelta(days=36500)


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


class MonthlyDayTimeTrigger(Trigger):
    def __init__(self, day_of_month: int, at_time: str) -> None:
        self.day_of_month = day_of_month
        self.at_time = parse_hhmm(at_time)

    def next_after(self, now: datetime, *, seed: str, jitter_seconds: int) -> datetime:
        year = now.year
        month = now.month

        for _offset in range(13):
            last_day = calendar.monthrange(year, month)[1]
            target_day = min(self.day_of_month, last_day)
            candidate = now.replace(
                year=year,
                month=month,
                day=target_day,
                hour=self.at_time.hour,
                minute=self.at_time.minute,
                second=0,
                microsecond=0,
            )
            if candidate > now:
                return add_seconds(candidate, deterministic_jitter(jitter_seconds, seed))
            month += 1
            if month > 12:
                month = 1
                year += 1
        raise ValueError("Monthly schedule did not resolve within one year")
