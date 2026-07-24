"""Push Stellar assignee (email) → Jira Ticket Assignee."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import StellarSettings, get_stellar_settings
from app.jira.client import JiraAPIError, JiraClient
from app.stellar.user_map import (
    StellarJiraUserMap,
    account_id_for_email,
    email_for_account_id,
    load_stellar_jira_user_map,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def stellar_assignee_email(case: dict[str, Any]) -> str | None:
    """Stellar ``Assigned to`` → email (assignee_name preferred)."""
    for key in ("assignee_name", "assignee"):
        val = case.get(key)
        if val and "@" in str(val):
            return str(val).strip()
    return None


def jira_assignee_account_id(fields: dict[str, Any]) -> str | None:
    assignee = fields.get("assignee")
    if not isinstance(assignee, dict):
        return None
    aid = assignee.get("accountId")
    if aid and str(aid).strip():
        return str(aid).strip()
    return None


def jira_assignee_email(
    fields: dict[str, Any],
    *,
    user_map: StellarJiraUserMap | None = None,
) -> str | None:
    """Jira assignee → email (API email, else accountId map, else None)."""
    assignee = fields.get("assignee")
    if not isinstance(assignee, dict):
        return None
    email = assignee.get("emailAddress")
    if email and str(email).strip():
        return str(email).strip()
    if user_map is not None:
        return email_for_account_id(jira_assignee_account_id(fields), user_map)
    return None


def load_user_map_for_settings(st: StellarSettings | None = None) -> StellarJiraUserMap:
    st = st or get_stellar_settings()
    path = Path(st.stellar_jira_user_map_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return load_stellar_jira_user_map(path)


async def apply_stellar_assignee_to_jira(
    *,
    jira: JiraClient,
    issue_key: str,
    case: dict[str, Any],
    dry_run: bool = False,
    user_map: StellarJiraUserMap | None = None,
) -> dict[str, Any]:
    """When Stellar assignee email differs from Jira Assignee, update Jira by accountId."""
    user_map = user_map or load_user_map_for_settings()
    stellar_email = stellar_assignee_email(case)
    issue = await jira.get_issue(issue_key, fields=["assignee"])
    jira_fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    jira_account = jira_assignee_account_id(jira_fields)

    if not stellar_email:
        return {"skipped": True, "reason": "stellar_unassigned"}

    mapped_account = account_id_for_email(stellar_email, user_map)
    target_account = await jira.find_user_account_id_by_email(
        stellar_email,
        mapped_account_id=mapped_account,
    )
    if not target_account:
        return {
            "skipped": True,
            "reason": "jira_user_not_found",
            "assignee": stellar_email,
        }

    if jira_account and jira_account == target_account:
        return {
            "skipped": True,
            "reason": "already_in_sync",
            "assignee": stellar_email,
            "jira_account_id": jira_account,
        }

    if dry_run:
        return {
            "dry_run": True,
            "issue_key": issue_key,
            "would_set_assignee": stellar_email,
            "jira_account_id": target_account,
        }

    try:
        await jira.update_issue(issue_key, {"assignee": {"accountId": target_account}})
    except JiraAPIError as e:
        return {
            "ok": False,
            "issue_key": issue_key,
            "error": str(e),
            "http_status": e.status_code,
            "body": e.body,
        }

    return {
        "updated": True,
        "issue_key": issue_key,
        "assignee": stellar_email,
        "jira_account_id": target_account,
    }
