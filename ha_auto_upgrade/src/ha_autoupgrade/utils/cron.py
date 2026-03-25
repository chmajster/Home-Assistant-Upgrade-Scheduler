"""Small cron parser for 5-field expressions."""

from __future__ import annotations

from datetime import datetime, timedelta

_RANGES = (
    (0, 59),
    (0, 23),
    (1, 31),
    (1, 12),
    (0, 6),
)


def _expand_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            base, step_raw = part.split("/", maxsplit=1)
            step = int(step_raw)
        else:
            base = part
            step = 1

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_raw, end_raw = base.split("-", maxsplit=1)
            start, end = int(start_raw), int(end_raw)
        else:
            start = end = int(base)

        if start < minimum or end > maximum or start > end:
            raise ValueError(f"Invalid cron field {field}")
        values.update(range(start, end + 1, step))
    return values


def _normalize_weekdays(values: set[int]) -> set[int]:
    normalized: set[int] = set()
    for value in values:
        normalized.add(0 if value == 7 else value)
    return normalized


def next_cron_occurrence(expression: str, now: datetime) -> datetime:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"Unsupported cron expression: {expression}")

    minute_values = _expand_field(fields[0], *_RANGES[0])
    hour_values = _expand_field(fields[1], *_RANGES[1])
    day_values = _expand_field(fields[2], *_RANGES[2])
    month_values = _expand_field(fields[3], *_RANGES[3])
    weekday_values = _normalize_weekdays(_expand_field(fields[4], 0, 7))

    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = candidate + timedelta(days=366)
    while candidate <= deadline:
        if (
            candidate.minute in minute_values
            and candidate.hour in hour_values
            and candidate.day in day_values
            and candidate.month in month_values
            and candidate.weekday() in weekday_values
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(f"Cron expression did not resolve within one year: {expression}")
