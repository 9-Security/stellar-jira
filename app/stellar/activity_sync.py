"""Format Stellar case activities for Jira comment mirroring."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_JIRA_ECHO_PREFIX = "[Jira "
_ACTIVITY_META_PREFIX = "stellar_act_jira:"


def extract_activities_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [a for a in data if isinstance(a, dict)]


def activity_sync_key(case_id: str, activity: dict[str, Any]) -> str:
    parts = [
        str(case_id or "").strip(),
        str(activity.get("timestamp") or ""),
        str(activity.get("action") or ""),
        str(activity.get("field") or ""),
        str(activity.get("from") or ""),
        str(activity.get("to") or ""),
        str(activity.get("user") or ""),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return digest


def activity_meta_key(case_id: str, activity: dict[str, Any]) -> str:
    return f"{_ACTIVITY_META_PREFIX}{activity_sync_key(case_id, activity)}"


def _user_label(user: Any) -> str:
    s = str(user or "").strip()
    if not s:
        return "system"
    if "@" in s:
        return s
    if len(s) > 12:
        return f"{s[:8]}…"
    return s


def _format_ts(ms: Any, *, tz_name: str = "Asia/Taipei") -> str:
    try:
        ts = int(ms or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(ts / 1000.0, tz=tz).strftime("%Y-%m-%d %H:%M %Z")


def format_activity_jira_comment(
    activity: dict[str, Any],
    *,
    timezone_name: str = "Asia/Taipei",
) -> str | None:
    """Render one Stellar activity as Jira comment body, or None if skipped."""
    action = str(activity.get("action") or "").strip().lower()
    field = str(activity.get("field") or "").strip()
    user = _user_label(activity.get("user"))
    when = _format_ts(activity.get("timestamp"), tz_name=timezone_name)
    time_suffix = f" ({when})" if when else ""

    if action == "add" and field == "comment":
        text = str(activity.get("to") or "").strip()
        if not text or text.startswith(_JIRA_ECHO_PREFIX):
            return None
        return f"[Stellar Activity] {user} commented{time_suffix}:\n{text}"

    if action == "update" and field:
        frm = str(activity.get("from") if activity.get("from") is not None else "")
        to = str(activity.get("to") if activity.get("to") is not None else "")
        if field == "comment":
            return None
        return f"[Stellar Activity] {user} updated {field}: {frm} → {to}{time_suffix}"

    if action == "add" and field and field != "comment":
        to = str(activity.get("to") or "").strip()
        if not to:
            return None
        return f"[Stellar Activity] {user} added {field}: {to}{time_suffix}"

    detail = str(activity.get("to") or activity.get("from") or "").strip()
    if not action and not field and not detail:
        return None
    bits = [x for x in (action, field, detail) if x]
    return f"[Stellar Activity] {user}: {' '.join(bits)}{time_suffix}"


def sort_activities_chronologically(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(activities, key=lambda a: int(a.get("timestamp") or 0))
