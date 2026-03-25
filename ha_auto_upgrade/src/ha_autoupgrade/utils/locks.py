"""Simple filesystem process lock."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import os
from pathlib import Path
import time


class LockAcquisitionError(RuntimeError):
    """Raised when the runtime lock cannot be acquired."""


@dataclass(slots=True)
class ProcessLock(AbstractContextManager["ProcessLock"]):
    path: Path
    stale_after_seconds: int = 86400
    _fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age > self.stale_after_seconds:
                self.path.unlink(missing_ok=True)
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as err:
            raise LockAcquisitionError(f"Lock already exists: {self.path}") from err
        os.write(self._fd, f"pid={os.getpid()}\ncreated={int(time.time())}\n".encode("utf-8"))

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
