"""Push Stellar case fields → linked Jira ticket (mirror for duty-platform mode)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import StellarSettings
from app.jira.client import JiraAPIError, JiraClient
from app.stellar.jira_assignee_update import apply_stellar_assignee_to_jira
from app.stellar.jira_status_update import apply_stellar_status_to_jira

logger = logging.getLogger(__name__)


async def mirror_stellar_case_to_jira(
    *,
    jira: JiraClient,
    issue_key: str,
    case: dict[str, Any],
    st: StellarSettings,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mirror Stellar status / assignee onto an existing Jira issue."""
    result: dict[str, Any] = {"issue_key": issue_key, "dry_run": dry_run}
    updated = False

    if st.stellar_sync_stellar_to_jira_status and str(case.get("status") or "").strip():
        try:
            status_out = await apply_stellar_status_to_jira(
                jira=jira,
                issue_key=issue_key,
                stellar_status=str(case.get("status") or ""),
                st=st,
                dry_run=dry_run,
            )
            result["status"] = status_out
            if status_out.get("updated") or (dry_run and status_out.get("dry_run")):
                updated = True
            elif status_out.get("skipped") and status_out.get("reason") == "no_transition":
                logger.warning(
                    "mirror status workflow blocked issue_key=%s stellar_status=%s %s",
                    issue_key,
                    case.get("status"),
                    status_out.get("actions"),
                )
        except JiraAPIError as e:
            result["status_error"] = {
                "error": str(e),
                "http_status": e.status_code,
                "body": e.body,
            }
            return {"ok": False, **result}

    if st.stellar_sync_stellar_to_jira_assignee:
        try:
            assignee_out = await apply_stellar_assignee_to_jira(
                jira=jira,
                issue_key=issue_key,
                case=case,
                dry_run=dry_run,
            )
            result["assignee"] = assignee_out
            if assignee_out.get("updated") or (dry_run and assignee_out.get("dry_run")):
                updated = True
        except JiraAPIError as e:
            result["assignee_error"] = {
                "error": str(e),
                "http_status": e.status_code,
                "body": e.body,
            }
            return {"ok": False, **result}

    if updated:
        result["ok"] = True
        result["updated"] = True
    else:
        result["ok"] = True
        result["skipped"] = True
        result["reason"] = "already_in_sync"
    return result
