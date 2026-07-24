"""Apply DecisionResult to Jira fields and notification routing (no auto-isolation)."""

from __future__ import annotations

from typing import Any

from app.decision.models import DecisionResult


_PRIORITY_MAP = {
    "highest": {"name": "Highest"},
    "high": {"name": "High"},
    "medium": {"name": "Medium"},
    "low": {"name": "Low"},
    "lowest": {"name": "Lowest"},
}


def apply_decision_to_jira_fields(
    fields: dict[str, Any],
    decision: DecisionResult,
) -> dict[str, Any]:
    """Mutate a copy of Jira create fields with decision labels / priority / description notes."""
    out = dict(fields)
    labels = list(out.get("labels") or [])
    for label in decision.jira_labels:
        if label and label not in labels:
            labels.append(label)
    esc_label = f"decision-{decision.escalation.lower()}"
    if esc_label not in labels:
        labels.append(esc_label)
    if decision.playbook_id:
        pb_label = decision.playbook_id.lower().replace(" ", "-")[:40]
        if pb_label and pb_label not in labels:
            labels.append(pb_label)
    if decision.isolate_host and "isolation-advisory" not in labels:
        labels.append("isolation-advisory")
    out["labels"] = labels

    if decision.jira_priority:
        pkey = decision.jira_priority.strip().lower()
        if pkey in _PRIORITY_MAP:
            out["priority"] = dict(_PRIORITY_MAP[pkey])

    from app.config import get_stellar_settings

    if not get_stellar_settings().decision_append_jira_description:
        return out

    # Append decision block to plain description if we can detect ADF paragraphs
    note_lines = [
        "",
        "--- AIxSOC Decision ---",
        f"Action: {decision.action}",
        f"Escalation: {decision.escalation}",
        f"Playbook: {decision.playbook_id or '-'}",
        f"Notify customer: {decision.notify_customer}",
        f"Isolation advisory: {decision.isolate_host}",
        f"Confidence: {decision.confidence:.2f}",
        f"Rules: {', '.join(decision.rule_hits) or '-'}",
        f"Knowledge: {', '.join(decision.knowledge_hits[:8]) or '-'}",
        f"Summary: {decision.summary or '-'}",
    ]
    desc = out.get("description")
    if isinstance(desc, dict) and desc.get("type") == "doc":
        from app.jira.adf import plain_text_to_adf

        # Rebuild by extracting isn't trivial; append as extra paragraph nodes
        extra = plain_text_to_adf("\n".join(note_lines))
        content = list(desc.get("content") or [])
        content.extend(extra.get("content") or [])
        out["description"] = {"type": "doc", "version": 1, "content": content}
    return out


def should_create_ticket(decision: DecisionResult) -> bool:
    return decision.action in ("create_ticket", "escalate")


def should_notify_internal(decision: DecisionResult) -> bool:
    if decision.action in ("defer", "suppress"):
        return False
    return bool(decision.notify_internal)


def should_notify_customer(decision: DecisionResult) -> bool:
    if decision.action in ("defer", "suppress"):
        return False
    return bool(decision.notify_customer)
