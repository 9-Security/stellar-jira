"""Mirror Stellar case activities → Jira issue comments."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.config import StellarSettings
from app.jira.client import JiraAPIError, JiraClient
from app.stellar.activity_sync import (
    activity_meta_key,
    extract_activities_list,
    format_activity_jira_comment,
    sort_activities_chronologically,
)
from app.stellar.client import StellarClient
from app.sync.state import SyncState

logger = logging.getLogger(__name__)


def _parse_synced_at_ms(synced_at: str | None) -> int:
    if not synced_at or not str(synced_at).strip():
        return 0
    s = str(synced_at).strip()
    try:
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except ValueError:
        return 0


async def mirror_stellar_activities_to_jira(
    *,
    jira: JiraClient,
    issue_key: str,
    case_id: str,
    client: StellarClient,
    st: StellarSettings,
    state: SyncState,
    synced_at: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post new Stellar case activities as Jira comments (deduped in SQLite meta)."""
    result: dict[str, Any] = {
        "issue_key": issue_key,
        "case_id": case_id,
        "dry_run": dry_run,
        "posted": 0,
        "skipped": 0,
    }
    if not st.stellar_mirror_case_activity_to_jira:
        result["ok"] = True
        result["reason"] = "activity_mirror_disabled"
        return result

    try:
        raw = await client.get_case_activities(case_id)
    except Exception as e:
        return {"ok": False, "error": f"fetch activities: {e}", **result}

    activities = sort_activities_chronologically(extract_activities_list(raw))
    since_ms = 0
    if st.stellar_mirror_case_activity_since_link:
        since_ms = _parse_synced_at_ms(synced_at)

    max_n = int(st.stellar_mirror_case_activity_max_per_ticket)
    posted = 0
    skipped = 0
    posted_ids: list[str] = []

    for activity in activities:
        if max_n > 0 and posted >= max_n:
            break
        try:
            ts = int(activity.get("timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0
        if since_ms > 0 and ts > 0 and ts < since_ms:
            skipped += 1
            continue

        meta_key = activity_meta_key(case_id, activity)
        if state.get_meta(meta_key) == "1":
            skipped += 1
            continue

        body = format_activity_jira_comment(
            activity,
            timezone_name=st.stellar_case_id_timezone,
        )
        if not body:
            skipped += 1
            continue

        if dry_run:
            posted += 1
            posted_ids.append(meta_key)
            continue

        try:
            await jira.add_comment(issue_key, body)
        except JiraAPIError as e:
            return {
                "ok": False,
                "error": str(e),
                "http_status": e.status_code,
                "body": e.body,
                "posted": posted,
                "skipped": skipped,
                **{k: v for k, v in result.items() if k not in ("posted", "skipped")},
            }

        state.set_meta(meta_key, "1")
        posted += 1
        posted_ids.append(meta_key)

    result["ok"] = True
    result["posted"] = posted
    result["skipped"] = skipped
    if dry_run and posted_ids:
        result["would_post_keys"] = posted_ids[:5]
    if posted:
        result["updated"] = True
    return result
