"""In-process sliding-window rate limiter for auth endpoints."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import HTTPException


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str, *, max_attempts: int, window_seconds: int) -> bool:
        if max_attempts <= 0:
            return True
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            times = [t for t in self._hits[key] if t > cutoff]
            if len(times) >= max_attempts:
                self._hits[key] = times
                return False
            times.append(now)
            self._hits[key] = times
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_login_limiter = SlidingWindowRateLimiter()


def consume_login_attempt(
    ip: str | None,
    *,
    email: str | None = None,
    max_attempts: int,
    window_seconds: int,
) -> None:
    """Count every login/TOTP attempt (success or failure) before expensive work."""
    keys = [f"ip:{(ip or 'unknown').strip() or 'unknown'}"]
    normalized_email = str(email or "").strip().lower()
    if normalized_email:
        keys.append(f"email:{normalized_email}")
    for key in keys:
        if not _login_limiter.allow(
            key,
            max_attempts=max_attempts,
            window_seconds=window_seconds,
        ):
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts; try again later",
            )


def record_auth_failure(
    ip: str | None,
    *,
    email: str | None = None,
    max_attempts: int,
    window_seconds: int,
) -> None:
    """Backward-compatible alias; prefer consume_login_attempt at request start."""
    consume_login_attempt(
        ip,
        email=email,
        max_attempts=max_attempts,
        window_seconds=window_seconds,
    )


def reset_login_rate_limiter() -> None:
    _login_limiter.reset()


def check_login_rate_limit(
    ip: str | None,
    *,
    max_attempts: int,
    window_seconds: int,
) -> None:
    """Backward-compatible alias; prefer record_auth_failure on failed auth only."""
    record_auth_failure(
        ip,
        max_attempts=max_attempts,
        window_seconds=window_seconds,
    )
