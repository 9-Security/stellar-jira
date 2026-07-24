"""Mirror all linked Stellar cases → Jira (duty platform; not limited by inbound lookback)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_jira_settings, get_stellar_settings
from app.jira.client import JiraClient
from app.stellar.client import StellarClient
from app.stellar.jira_activity_mirror import mirror_stellar_activities_to_jira
from app.stellar.jira_mirror import mirror_stellar_case_to_jira
from app.sync.state import SyncState

REPO_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def _persist_mirror_summary(state: SyncState, source_id: str, out: dict[str, Any]) -> None:
    sfx = f":{source_id}"
    state.set_meta("last_mirror_finished_at" + sfx, datetime.now(timezone.utc).isoformat())
    state.set_meta("last_mirror_ok" + sfx, "1" if out.get("ok") else "0")
    state.set_meta("last_mirror_total" + sfx, str(int(out.get("total") or 0)))
    state.set_meta("last_mirror_updated" + sfx, str(int(out.get("updated") or 0)))
    state.set_meta("last_mirror_skipped" + sfx, str(int(out.get("skipped") or 0)))
    state.set_meta("last_mirror_errors" + sfx, str(len(out.get("errors") or [])))


async def run_stellar_to_jira_mirror_cycle(*, dry_run: bool = False) -> dict[str, Any]:
    """
    For each linked ``(case_id, jira_key)``, read Stellar and mirror status/assignee to Jira.
    """
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    st = get_stellar_settings()
    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"
    state_path = REPO_ROOT / st.stellar_sync_state_db
    state = SyncState(state_path)
    state.init(legacy_source_id=source_id)

    linked = state.list_linked_jira_keys(source_id)
    max_n = int(st.stellar_mirror_max_issues_per_cycle)
    if max_n > 0 and len(linked) > max_n:
        linked = linked[:max_n]

    updated = 0
    activity_posted = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    per: list[dict[str, Any]] = []

    if not st.stellar_base_url or not st.stellar_api_key:
        return {
            "ok": False,
            "source_id": source_id,
            "dry_run": dry_run,
            "total": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [{"error": "STELLAR_BASE_URL/STELLAR_API_KEY not configured"}],
            "results": [],
        }

    jira_s = get_jira_settings()
    client = StellarClient(
        base_url=str(st.stellar_base_url),
        api_key=st.stellar_api_key,
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
    )

    async with JiraClient(jira_s) as jira:
        async with client:
            for case_id, jira_key in linked:
                t0 = time.monotonic()
                try:
                    raw = await client.get_case(case_id)
                    case = client.extract_case_one(raw) or {}
                    if not case:
                        errors.append(
                            {
                                "jira_key": jira_key,
                                "case_id": case_id,
                                "error": "stellar case not found",
                            }
                        )
                        continue
                    one = await mirror_stellar_case_to_jira(
                        jira=jira,
                        issue_key=jira_key,
                        case=case,
                        st=st,
                        dry_run=dry_run,
                    )
                    act = await mirror_stellar_activities_to_jira(
                        jira=jira,
                        issue_key=jira_key,
                        case_id=case_id,
                        client=client,
                        st=st,
                        state=state,
                        synced_at=state.get_link_synced_at(source_id, case_id),
                        dry_run=dry_run,
                    )
                    one["activities"] = act
                except Exception as e:
                    logger.exception("mirror failed jira_key=%s case_id=%s", jira_key, case_id)
                    errors.append({"jira_key": jira_key, "case_id": case_id, "error": str(e)})
                    continue

                if not one.get("ok"):
                    errors.append(
                        {
                            "jira_key": jira_key,
                            "case_id": case_id,
                            "error": one.get("status_error") or one.get("assignee_error") or one.get("error"),
                        }
                    )
                elif not act.get("ok", True):
                    errors.append(
                        {
                            "jira_key": jira_key,
                            "case_id": case_id,
                            "error": act.get("error"),
                            "http_status": act.get("http_status"),
                        }
                    )
                elif one.get("updated") or int((one.get("activities") or {}).get("posted") or 0) > 0:
                    updated += 1
                    activity_posted += int((one.get("activities") or {}).get("posted") or 0)
                else:
                    skipped += 1

                per.append(
                    {
                        "jira_key": jira_key,
                        "case_id": case_id,
                        "ok": one.get("ok"),
                        "updated": bool(one.get("updated")),
                        "activities_posted": int((one.get("activities") or {}).get("posted") or 0),
                        "skipped": bool(one.get("skipped")) and not (one.get("activities") or {}).get("posted"),
                        "reason": one.get("reason"),
                        "elapsed_ms": int((time.monotonic() - t0) * 1000),
                    }
                )

    out: dict[str, Any] = {
        "ok": not errors,
        "source_id": source_id,
        "dry_run": dry_run,
        "total": len(linked),
        "updated": updated,
        "activity_posted": activity_posted,
        "skipped": skipped,
        "errors": errors,
        "results": per,
    }
    _persist_mirror_summary(state, source_id, out)
    return out
