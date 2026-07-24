"""Bidirectional status: Jira Workflow + 事件狀態 custom field ↔ Stellar case.status."""

from __future__ import annotations

from typing import Any

from app.stellar.jira_draft import _stellar_status_to_jira_option
from app.stellar.workflow_status_map import (
    WorkflowStatusMap,
    load_workflow_status_map,
    map_jira_workflow_to_stellar,
    map_stellar_to_jira_workflow,
)

_STELLAR_STATUSES = frozenset({"New", "Escalated", "In Progress", "Resolved", "Cancelled"})


def normalize_status_label(label: str | None) -> str | None:
    if not label or not str(label).strip():
        return None
    mapped = _stellar_status_to_jira_option(str(label).strip())
    if mapped and mapped in _STELLAR_STATUSES:
        return mapped
    return None


def jira_select_field_value(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("value", "name"):
            v = raw.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None
    s = str(raw).strip()
    return s or None


def jira_workflow_status_name(fields: dict[str, Any]) -> str | None:
    """Jira built-in Ticket Status (workflow ``fields.status.name``)."""
    raw = fields.get("status")
    if isinstance(raw, dict):
        name = raw.get("name")
        if name and str(name).strip():
            return str(name).strip()
    return None


def jira_custom_status_label(fields: dict[str, Any], status_field_id: str) -> str | None:
    """Jira 事件狀態 custom field label (same option names as Stellar status)."""
    if not status_field_id:
        return None
    return jira_select_field_value(fields.get(status_field_id))


def stellar_status_from_jira_workflow(
    fields: dict[str, Any],
    *,
    workflow_map: WorkflowStatusMap | None = None,
) -> str | None:
    """Jira Ticket Status → Stellar ``status`` via ``stellar_jira_workflow_status_map.json``."""
    wmap = workflow_map or load_workflow_status_map()
    wf_name = jira_workflow_status_name(fields)
    if not wf_name:
        return None
    mapped = map_jira_workflow_to_stellar(wf_name, wmap)
    if mapped and mapped in _STELLAR_STATUSES:
        return mapped
    return normalize_status_label(wf_name)


def stellar_status_from_jira_custom(
    fields: dict[str, Any],
    status_field_id: str,
) -> str | None:
    """Jira 事件狀態 → Stellar ``status`` (direct label match)."""
    label = jira_custom_status_label(fields, status_field_id)
    return normalize_status_label(label)


def stellar_status_from_jira_fields(
    fields: dict[str, Any],
    *,
    status_field_id: str = "",
    prefer_workflow: bool = True,
    sync_custom_status: bool = True,
    workflow_map: WorkflowStatusMap | None = None,
) -> str | None:
    """
    Resolve Stellar status from Jira workflow and/or 事件狀態 custom field.

    When both map to different values, ``prefer_workflow`` chooses the winner.
    """
    wf = stellar_status_from_jira_workflow(fields, workflow_map=workflow_map)
    if not sync_custom_status or not status_field_id:
        return wf
    custom = stellar_status_from_jira_custom(fields, status_field_id)
    if not wf:
        return custom
    if not custom:
        return wf
    if wf == custom:
        return wf
    return wf if prefer_workflow else custom


def stellar_jira_custom_status_option(stellar_status: str) -> str | None:
    """Stellar ``status`` → Jira 事件狀態 option label."""
    return _stellar_status_to_jira_option(str(stellar_status or "").strip())


def needs_jira_workflow_status_update(
    jira_fields: dict[str, Any],
    *,
    stellar_status: str,
    workflow_map: WorkflowStatusMap | None = None,
) -> bool:
    target = normalize_status_label(stellar_status)
    if not target:
        return False
    wmap = workflow_map or load_workflow_status_map()
    wf_target = map_stellar_to_jira_workflow(target, wmap)
    if not wf_target:
        return False
    current_wf = str(jira_workflow_status_name(jira_fields) or "")
    return current_wf.lower() != wf_target.lower()


def needs_jira_custom_status_update(
    jira_fields: dict[str, Any],
    *,
    stellar_status: str,
    status_field_id: str,
) -> bool:
    target = normalize_status_label(stellar_status)
    if not target or not status_field_id:
        return False
    option = stellar_jira_custom_status_option(target)
    if not option:
        return False
    current = jira_custom_status_label(jira_fields, status_field_id)
    return not current or current.lower() != option.lower()
