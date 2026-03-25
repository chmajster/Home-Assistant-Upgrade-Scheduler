"""Date and time helpers."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import hashlib
import random

from dateutil import tz

from ha_autoupgrade.constants import DEFAULT_WEEKDAYS

_WEEKDAY_MAP = {day: index for index, day in enumerate(DEFAULT_WEEKDAYS)}


def utc_now() -> datetime:
    return datetime.now(UTC)


def local_now() -> datetime:
    return datetime.now(tz.tzlocal())


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def parse_hhmm(value: str) -> time:
    parts = value.split(":", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM value: {value}")
    return time(hour=int(parts[0]), minute=int(parts[1]))


def parse_weekday_time(value: str) -> tuple[int, time]:
    weekday, hm = value.split("@", maxsplit=1)
    weekday = weekday.strip().lower()
    if weekday not in _WEEKDAY_MAP:
        raise ValueError(f"Invalid weekday value: {weekday}")
    return _WEEKDAY_MAP[weekday], parse_hhmm(hm.strip())


def within_time_window(now: datetime, window: str) -> bool:
    if not window:
        return True
    start_raw, end_raw = window.split("-", maxsplit=1)
    start = parse_hhmm(start_raw.strip())
    end = parse_hhmm(end_raw.strip())
    current = now.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def blackout_match(now: datetime, blackout_dates: list[str]) -> str | None:
    date_str = now.date().isoformat()
    for entry in blackout_dates:
        raw_date, _, label = entry.partition(":")
        if raw_date.strip() == date_str:
            return label.strip() or raw_date.strip()
    return None


def deterministic_jitter(max_seconds: int, seed: str) -> int:
    if max_seconds <= 0:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:8], 16))
    return rng.randint(0, max_seconds)


def add_seconds(value: datetime, seconds: int) -> datetime:
    return value + timedelta(seconds=seconds)
