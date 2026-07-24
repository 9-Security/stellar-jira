"""Decision Layer output models (machine-verifiable, audit-ready)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DecisionAction = Literal["create_ticket", "defer", "suppress", "escalate"]
EscalationLevel = Literal["L1", "L2", "IR"]


@dataclass
class DecisionResult:
    """Structured security decision for one Stellar case."""

    action: DecisionAction = "create_ticket"
    escalation: EscalationLevel = "L1"
    notify_customer: bool = False
    notify_internal: bool = True
    isolate_host: bool = False  # advisory only — never auto-executed in v0.2
    playbook_id: str = ""
    confidence: float = 0.0
    rule_hits: list[str] = field(default_factory=list)
    knowledge_hits: list[str] = field(default_factory=list)
    jira_labels: list[str] = field(default_factory=list)
    jira_priority: str | None = None
    summary: str = ""
    ai_sections: dict[str, Any] | None = None
    context_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DecisionResult:
        if not isinstance(data, dict):
            return cls()
        action = str(data.get("action") or "create_ticket")
        if action not in ("create_ticket", "defer", "suppress", "escalate"):
            action = "create_ticket"
        escalation = str(data.get("escalation") or "L1")
        if escalation not in ("L1", "L2", "IR"):
            escalation = "L1"
        conf = data.get("confidence")
        try:
            confidence = max(0.0, min(1.0, float(conf if conf is not None else 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        ai = data.get("ai_sections")
        ctx = data.get("context_snapshot")
        return cls(
            action=action,  # type: ignore[arg-type]
            escalation=escalation,  # type: ignore[arg-type]
            notify_customer=bool(data.get("notify_customer")),
            notify_internal=bool(data.get("notify_internal", True)),
            isolate_host=bool(data.get("isolate_host")),
            playbook_id=str(data.get("playbook_id") or ""),
            confidence=confidence,
            rule_hits=[str(x) for x in (data.get("rule_hits") or []) if str(x).strip()],
            knowledge_hits=[str(x) for x in (data.get("knowledge_hits") or []) if str(x).strip()],
            jira_labels=[str(x) for x in (data.get("jira_labels") or []) if str(x).strip()],
            jira_priority=(str(data["jira_priority"]).strip() or None) if data.get("jira_priority") else None,
            summary=str(data.get("summary") or ""),
            ai_sections=ai if isinstance(ai, dict) else None,
            context_snapshot=ctx if isinstance(ctx, dict) else {},
        )
