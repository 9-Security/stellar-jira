"""Allocate middleware case IDs: ``{prefix}-{customer_code}-{yymmdd}-{seq:03d}``."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.sync.state import SyncState


def case_seq_meta_key(customer_code: str, date_yymmdd: str) -> str:
    return f"case_seq:{customer_code}:{date_yymmdd}"


def format_case_id(*, prefix: str, customer_code: str, date_yymmdd: str, seq: int) -> str:
    p = prefix.strip().upper()
    cc = customer_code.strip().upper()
    return f"{p}-{cc}-{date_yymmdd}-{seq:03d}"


def _today_yymmdd(tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"Unknown SYNC_CASE_ID_TIMEZONE: {tz_name!r}") from e
    return datetime.now(tz).strftime("%y%m%d")


def peek_next_case_id(
    state: SyncState,
    *,
    prefix: str,
    customer_code: str,
    timezone_name: str,
    seq_offset: int = 1,
) -> str:
    """Next ID without incrementing (for build fields / dry-run previews).

    Sequence is 001, 002, … per ``customer_code`` per calendar day (``SYNC_CASE_ID_TIMEZONE``);
    ``seq_offset=1`` is the next live id.
    """
    date_yymmdd = _today_yymmdd(timezone_name)
    key = case_seq_meta_key(customer_code, date_yymmdd)
    cur = int(state.get_meta(key) or "0")
    return format_case_id(
        prefix=prefix,
        customer_code=customer_code,
        date_yymmdd=date_yymmdd,
        seq=cur + max(1, seq_offset),
    )


def commit_case_id(
    state: SyncState,
    *,
    prefix: str,
    customer_code: str,
    timezone_name: str,
) -> str:
    """Allocate and persist the next case id (call only after Jira create succeeds)."""
    date_yymmdd = _today_yymmdd(timezone_name)
    seq = state.increment_case_sequence(customer_code, date_yymmdd)
    return format_case_id(prefix=prefix, customer_code=customer_code, date_yymmdd=date_yymmdd, seq=seq)
