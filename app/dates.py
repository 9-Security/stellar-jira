"""Calendar date helpers shared by reports and APIs (no Cortex dependency)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_MONTH_ABBR = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def parse_iso_date(s: str) -> date:
    return date.fromisoformat(s.strip())


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(month: str) -> tuple[date, date]:
    """``YYYY-MM`` → inclusive first/last calendar day of that month."""
    m = _MONTH_RE.match(month.strip())
    if not m:
        raise ValueError(f"Invalid month {month!r}; use YYYY-MM")
    year, mon = int(m.group(1)), int(m.group(2))
    if not 1 <= mon <= 12:
        raise ValueError(f"Invalid month {month!r}")
    start_d = date(year, mon, 1)
    if mon == 12:
        end_d = date(year, 12, 31)
    else:
        end_d = date(year, mon + 1, 1) - timedelta(days=1)
    return start_d, end_d


def previous_period_dates(start_d: date, end_d: date) -> tuple[date, date]:
    """Same-length window immediately before ``start_d`` (for MoM)."""
    days = (end_d - start_d).days + 1
    prev_end = start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return prev_start, prev_end


def inclusive_creation_time_range_ms(start_d: date, end_d: date, tz: ZoneInfo) -> tuple[int, int]:
    if end_d < start_d:
        raise ValueError("end_date must be on or after start_date")
    start_local = datetime.combine(start_d, datetime.min.time(), tzinfo=tz)
    end_exclusive_local = datetime.combine(end_d + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    end_inclusive_ms = int(end_exclusive_local.timestamp() * 1000) - 1
    start_ms = int(start_local.timestamp() * 1000)
    return start_ms, end_inclusive_ms


def normalize_epoch_ms(val: object) -> int | None:
    """Cortex timestamps are usually epoch ms; tolerate seconds or numeric strings."""
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            n = float(s)
        except ValueError:
            return None
    elif isinstance(val, (int, float)) and not isinstance(val, bool):
        n = float(val)
    else:
        return None
    if n > 1e12:
        return int(n)
    if n > 1e9:
        return int(n * 1000.0)
    return int(n * 1000.0)


def _ordinal_day(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def format_detection_time(ms: Any, *, timezone_name: str = "Asia/Taipei") -> str:
    """SOC notify style: ``Apr 20th 2026 17:59:56`` in the given timezone."""
    normalized = normalize_epoch_ms(ms)
    if normalized is None:
        return ""
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    dt = datetime.fromtimestamp(normalized / 1000.0, tz=tz)
    return f"{_MONTH_ABBR[dt.month - 1]} {_ordinal_day(dt.day)} {dt.year} {dt:%H:%M:%S}"
