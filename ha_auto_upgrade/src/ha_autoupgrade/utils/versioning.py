"""Version helpers and list parsing."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

_DIGIT_RE = re.compile(r"\d+")


def _numeric_segments(value: str) -> list[int]:
    return [int(part) for part in _DIGIT_RE.findall(value)]


def compare_versions(left: str, right: str) -> int:
    left_segments = _numeric_segments(left)
    right_segments = _numeric_segments(right)
    max_len = max(len(left_segments), len(right_segments), 1)
    left_segments += [0] * (max_len - len(left_segments))
    right_segments += [0] * (max_len - len(right_segments))
    if left_segments < right_segments:
        return -1
    if left_segments > right_segments:
        return 1
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def is_patch_upgrade(current: str, target: str) -> bool:
    current_segments = _numeric_segments(current)[:3]
    target_segments = _numeric_segments(target)[:3]
    current_segments += [0] * (3 - len(current_segments))
    target_segments += [0] * (3 - len(target_segments))
    return (
        target_segments > current_segments
        and current_segments[0] == target_segments[0]
        and current_segments[1] == target_segments[1]
        and target_segments[2] > current_segments[2]
    )


def parse_mapping_entries(entries: Iterable[str], label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for entry in entries:
        key, separator, value = entry.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not key or not value:
            raise ValueError(f"Invalid {label} entry: {entry}")
        parsed[key] = value
    return parsed


def rollout_bucket(seed: str, value: str) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100
