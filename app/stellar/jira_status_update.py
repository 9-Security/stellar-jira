"""Push Stellar case.status → Jira Workflow + 事件狀態 custom field."""

from __future__ import annotations

import logging
from typing import Any

from app.config import StellarSettings
from app.jira.client import JiraAPIError, JiraClient
from app.stellar.status_sync import (
    jira_custom_status_label,
    jira_workflow_status_name,
    needs_jira_custom_status_update,
    needs_jira_workflow_status_update,
    normalize_status_label,
    stellar_jira_custom_status_option,
)
from app.stellar.workflow_status_map import load_workflow_status_map, map_stellar_to_jira_workflow

logger = logging.getLogger(__name__)


async def _transition_to_workflow_name(jira: JiraClient, issue_key: str, workflow_target: str) -> str | None:
    want = str(workflow_target or "").strip()
    if not want:
        return None
    transitions = await jira.get_transitions(issue_key)
    for tr in transitions:
        to = tr.get("to") if isinstance(tr.get("to"), dict) else {}
        to_name = str(to.get("name") or "").strip()
        if to_name.lower() == want.lower():
            tid = str(tr.get("id") or "").strip()
            if tid:
                await jira.transition_issue(issue_key, tid)
                return tid
    return None


async def apply_stellar_status_to_jira(
    *,
    jira: JiraClient,
    issue_key: str,
    stellar_status: str,
    st: StellarSettings,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Stellar ``status`` → Jira Workflow transition + 事件狀態 custom field."""
    sync_workflow = st.stellar_sync_jira_workflow_status
    sync_custom = st.stellar_sync_jira_custom_status
    if not sync_workflow and not sync_custom:
        return {"skipped": True, "reason": "status_sync_disabled"}

    target = normalize_status_label(stellar_status)
    if not target:
        return {"skipped": True, "reason": "unmapped_stellar_status", "stellar_status": stellar_status}

    status_field_id = st.stellar_jira_status_field or "customfield_10061"
    fetch_fields = ["status"]
    if sync_custom:
        fetch_fields.append(status_field_id)

    issue = await jira.get_issue(issue_key, fields=fetch_fields)
    jira_fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}

    # When Jira→Stellar status writeback is on, do not reopen a terminal Jira ticket from Stellar
    # (alert noise bumps modified_at; inbound mirror must not undo Jira Resolved before writeback).
    if st.stellar_writeback_sync_status and not st.stellar_jira_master_after_link:
        jira_wf = jira_workflow_status_name(jira_fields)
        terminal = {"Resolved", "Closed", "Done", "Cancelled"}
        if jira_wf and jira_wf in terminal and target not in {"Resolved", "Cancelled"}:
            return {
                "skipped": True,
                "reason": "jira_terminal_writeback_owns",
                "stellar_status": target,
                "jira_ticket_status": jira_wf,
            }

    need_workflow = sync_workflow and needs_jira_workflow_status_update(jira_fields, stellar_status=target)
    need_custom = sync_custom and needs_jira_custom_status_update(
        jira_fields, stellar_status=target, status_field_id=status_field_id
    )

    if not need_workflow and not need_custom:
        return {
            "skipped": True,
            "reason": "already_in_sync",
            "stellar_status": target,
            "jira_ticket_status": jira_workflow_status_name(jira_fields),
            "jira_custom_status": jira_custom_status_label(jira_fields, status_field_id),
        }

    actions: dict[str, Any] = {"stellar_status": target}
    if dry_run:
        if need_workflow:
            wmap = load_workflow_status_map()
            actions["workflow_target"] = map_stellar_to_jira_workflow(target, wmap)
        if need_custom:
            actions["custom_status_target"] = stellar_jira_custom_status_option(target)
        return {"dry_run": True, "issue_key": issue_key, "actions": actions}

    updated = False
    workflow_failed = False

    if need_workflow:
        wmap = load_workflow_status_map()
        workflow_target = map_stellar_to_jira_workflow(target, wmap)
        if not workflow_target:
            actions["workflow_skipped"] = "no_workflow_mapping"
        else:
            actions["workflow_target"] = workflow_target
            try:
                tid = await _transition_to_workflow_name(jira, issue_key, workflow_target)
                if tid:
                    actions["transition_id"] = tid
                    updated = True
                else:
                    workflow_failed = True
                    actions["transition_warning"] = f"no transition to {workflow_target!r}"
                    logger.warning(
                        "no Jira transition to %s for %s (Stellar %s)",
                        workflow_target,
                        issue_key,
                        target,
                    )
            except JiraAPIError as e:
                return {
                    "ok": False,
                    "issue_key": issue_key,
                    "error": str(e),
                    "http_status": e.status_code,
                    "body": e.body,
                }

    if need_custom:
        option = stellar_jira_custom_status_option(target)
        if option:
            actions["custom_status_target"] = option
            try:
                await jira.update_issue(issue_key, {status_field_id: {"value": option}})
                actions["custom_status_updated"] = option
                updated = True
            except JiraAPIError as e:
                if updated:
                    actions["custom_status_error"] = str(e)
                    logger.warning(
                        "custom status update failed after workflow change issue_key=%s: %s",
                        issue_key,
                        e,
                    )
                else:
                    return {
                        "ok": False,
                        "issue_key": issue_key,
                        "error": str(e),
                        "http_status": e.status_code,
                        "body": e.body,
                    }

    if updated:
        return {"updated": True, "issue_key": issue_key, "actions": actions}
    if workflow_failed:
        return {"skipped": True, "reason": "no_transition", "issue_key": issue_key, "actions": actions}
    return {"skipped": True, "reason": "no_changes", "issue_key": issue_key, "actions": actions}
