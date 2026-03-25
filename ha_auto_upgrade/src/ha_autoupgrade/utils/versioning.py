"""Version helpers and list parsing."""

from __future__ import annotations

import hashlib
from typing import Iterable

from packaging.version import InvalidVersion, Version


def parse_version(value: str) -> Version | None:
    try:
        return Version(value)
    except InvalidVersion:
        return None


def compare_versions(left: str, right: str) -> int:
    left_version = parse_version(left)
    right_version = parse_version(right)
    if left_version and right_version:
        if left_version < right_version:
            return -1
        if left_version > right_version:
            return 1
        return 0
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def is_patch_upgrade(current: str, target: str) -> bool:
    current_version = parse_version(current)
    target_version = parse_version(target)
    if current_version is None or target_version is None:
        return False
    current_release = list(current_version.release) + [0, 0, 0]
    target_release = list(target_version.release) + [0, 0, 0]
    return (
        target_version > current_version
        and current_release[0] == target_release[0]
        and current_release[1] == target_release[1]
        and target_release[2] > current_release[2]
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
