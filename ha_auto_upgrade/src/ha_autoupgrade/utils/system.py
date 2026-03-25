"""System inspection helpers."""

from __future__ import annotations

from pathlib import Path
import shutil
import socket


def free_disk_mb(path: Path) -> int:
    usage = shutil.disk_usage(path)
    return int(usage.free / (1024 * 1024))


def load_average_1m() -> float | None:
    try:
        return float(__import__("os").getloadavg()[0])
    except (AttributeError, OSError):
        return None


def free_memory_mb() -> int | None:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return None
    values: dict[str, int] = {}
    for line in meminfo_path.read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", maxsplit=1)
        parts = raw.strip().split()
        if parts:
            values[key] = int(parts[0])
    available_kb = values.get("MemAvailable") or values.get("MemFree")
    if available_kb is None:
        return None
    return int(available_kb / 1024)


def tcp_connectivity(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
