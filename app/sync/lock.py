"""Exclusive lock so only one Stellar↔Jira sync/writeback runs per state DB at a time."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SyncLockError(RuntimeError):
    """Another process holds the sync lock."""


@contextmanager
def sync_process_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise SyncLockError(
                f"Another sync is already running (lock: {lock_path}). "
                "Stop duplicate poll/automation/API sync processes."
            ) from e
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
