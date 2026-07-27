"""Poll watermark helpers — always use XCockpit API UTC timestamps."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

WATERMARK_ALERTS = "xcockpit_poll_alerts_after"
WATERMARK_INCIDENTS = "xcockpit_poll_incidents_after"
WATERMARK_LEGACY = "xcockpit_poll_created_after"


def parse_api_datetime(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_watermark(
    state: Any,
    key: str,
    *,
    legacy_key: str | None = WATERMARK_LEGACY,
    default: datetime,
) -> datetime:
    raw = state.get_watermark(key)
    if not raw and legacy_key:
        raw = state.get_watermark(legacy_key)
        if raw:
            logger.info("Migrating legacy watermark %s -> %s", legacy_key, key)
    if raw:
        try:
            dt = parse_api_datetime(raw)
            if dt > datetime.now(timezone.utc) + timedelta(minutes=5):
                logger.warning(
                    "Watermark %s is in the future (%s); using lookback",
                    key,
                    dt.isoformat(),
                )
                return default
            return dt
        except ValueError:
            logger.warning("Invalid watermark %s=%r; using lookback", key, raw)
    return default


def bump_alert_watermark(current: datetime, item: dict[str, Any]) -> datetime:
    """Advance alert cursor using Alert List ``created`` only (never ReportTime)."""
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return current
    ref = payload.get("_xcockpit_alert_ref")
    if not isinstance(ref, dict):
        return current
    created = ref.get("created")
    if not created:
        return current
    try:
        dt = parse_api_datetime(str(created))
    except ValueError:
        logger.warning("Invalid alert ref created=%r", created)
        return current
    return dt if dt > current else current


def bump_incident_watermark(current: datetime, item: dict[str, Any]) -> datetime:
    """Advance incident cursor using list API ``created`` / ``Created`` only."""
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return current
    best = current
    for key in ("created", "Created"):
        raw = payload.get(key)
        if not raw:
            continue
        try:
            dt = parse_api_datetime(str(raw))
        except ValueError:
            logger.warning("Invalid incident %s=%r", key, raw)
            continue
        if dt > best:
            best = dt
    return best
