"""Decision pipeline: knowledge → rules → optional AI enrichment → DecisionResult."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.ai.stellar_context import build_stellar_soc_ai_context
from app.config import NotifySettings, get_notify_settings
from app.decision.actions import (
    apply_decision_to_jira_fields,
    should_create_ticket,
    should_notify_customer,
    should_notify_internal,
)
from app.decision.ai_bridge import brief_decision_for_ai, generate_ai_aligned_with_decision
from app.decision.knowledge import enrich_knowledge, load_assets, load_knowledge
from app.decision.models import DecisionResult
from app.decision.rules import apply_rules, load_decision_rules
from app.decision.store import DecisionStore

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_knowledge_cfg() -> dict:
    try:
        from app.config import get_stellar_settings

        return load_knowledge(get_stellar_settings().decision_knowledge_path)
    except Exception:
        return load_knowledge()


def load_assets_cfg() -> dict:
    try:
        from app.config import get_stellar_settings

        return load_assets(get_stellar_settings().decision_assets_path)
    except Exception:
        return load_assets()


def _decision_enabled() -> bool:
    try:
        from app.config import get_stellar_settings

        return bool(get_stellar_settings().decision_enabled)
    except Exception:
        return True


def get_decision_store(state_db_path: Path | str | None = None) -> DecisionStore:
    from app.config import get_stellar_settings

    st = get_stellar_settings()
    if state_db_path:
        path = Path(state_db_path)
    else:
        path = REPO_ROOT / st.stellar_sync_state_db
    store = DecisionStore(path)
    store.init()
    return store


async def evaluate_case_decision(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    source_id: str,
    customer_code: str = "",
    middleware_case_id: str = "",
    jira_key: str = "",
    store: DecisionStore | None = None,
    notify_settings: NotifySettings | None = None,
    run_ai: bool = False,
    persist: bool = True,
    snapshot_id: str | None = None,
) -> DecisionResult:
    """
    Run Knowledge + Rules (+ optional AI) and optionally persist a decision_events row.

    AI is advisory: it fills ``ai_sections`` but does not override rule ``action``.
    """
    ns = notify_settings or get_notify_settings()
    history: list[dict[str, Any]] = []
    active_store = store
    if active_store is None and persist:
        try:
            active_store = get_decision_store()
        except Exception as e:
            logger.warning("decision store init failed: %s", e)
            active_store = None

    if active_store is not None:
        try:
            history = active_store.list_similar_contexts(
                source_id=source_id,
                customer_code=customer_code,
                limit=50,
            )
        except Exception as e:
            logger.warning("decision history load failed: %s", e)

    knowledge = enrich_knowledge(
        case=case,
        bundle=bundle,
        customer_code=customer_code,
        history=history,
        knowledge=load_knowledge_cfg(),
        assets=load_assets_cfg(),
    )

    rules_path = None
    try:
        from app.config import get_stellar_settings

        st = get_stellar_settings()
        rp = (st.decision_rules_path or "").strip()
        rules_path = rp or None
    except Exception:
        rules_path = None
    rules_doc = load_decision_rules(rules_path)

    decision = apply_rules(
        case=case,
        bundle=bundle,
        customer_code=customer_code,
        asset_criticality=str(knowledge.get("asset_criticality") or "medium"),
        rules_doc=rules_doc,
    )
    decision.knowledge_hits = list(knowledge.get("knowledge_hits") or [])

    # Knowledge may suggest playbook / escalate when rules used default / generic playbook,
    # or refine IR malware → blocked review playbook.
    suggested_pb = str(knowledge.get("suggested_playbook") or "").strip()
    replaceable = {
        "",
        "PB-DEFAULT",
        "PB-L1-MED",
        "PB-L2-HIGH",
        "PB-L1-PERSIST",
        "PB-L1-EXEC",
    }
    if suggested_pb and (
        decision.playbook_id in replaceable
        or (
            decision.playbook_id == "PB-IR-MALWARE"
            and suggested_pb == "PB-IR-MALWARE-BLOCKED"
        )
    ):
        decision.playbook_id = suggested_pb
        if suggested_pb == "PB-IR-MALWARE-BLOCKED":
            decision.isolate_host = False
            if "decision-blocked-review" not in decision.jira_labels:
                decision.jira_labels = list(decision.jira_labels) + ["decision-blocked-review"]
    escalate_hint = str(knowledge.get("escalate_hint") or "").strip().upper()
    if escalate_hint in ("L2", "IR") and decision.escalation == "L1":
        decision.escalation = escalate_hint  # type: ignore[assignment]
        if escalate_hint == "IR" and decision.action == "create_ticket":
            decision.action = "escalate"
    if str(knowledge.get("asset_criticality") or "").lower() in ("high", "critical"):
        if decision.escalation == "L1":
            decision.escalation = "L2"
        if not decision.notify_customer and decision.action in ("create_ticket", "escalate"):
            decision.notify_customer = True
            decision.summary = (decision.summary + "; high-criticality asset").strip("; ")

    context = build_stellar_soc_ai_context(
        case=case,
        bundle=bundle,
        middleware_case_id=middleware_case_id,
        customer_code=customer_code,
        decision=brief_decision_for_ai(decision),
    )
    context["decision_preview"] = {
        "action": decision.action,
        "escalation": decision.escalation,
        "playbook_id": decision.playbook_id,
        "asset_criticality": knowledge.get("asset_criticality"),
        "similar_cases": knowledge.get("similar_cases"),
        "sigma_hits": [
            {"id": s.get("id"), "title": s.get("title")} for s in (knowledge.get("sigma_hits") or [])
        ],
    }
    decision.context_snapshot = context

    if run_ai and ns.soc_notify_ai_configured:
        try:
            ai_status = await generate_ai_aligned_with_decision(
                case=case,
                bundle=bundle,
                middleware_case_id=middleware_case_id,
                customer_code=customer_code,
                decision=decision,
                settings=ns,
            )
            if ai_status.get("ok"):
                decision.ai_sections = {
                    "executive_summary": ai_status.get("executive_summary"),
                    "event_description": ai_status.get("event_description"),
                    "recommended_actions": ai_status.get("recommended_actions"),
                }
        except Exception as e:
            logger.warning("decision AI enrichment failed: %s", e)

    if persist and active_store is not None:
        try:
            event_id = active_store.record_decision(
                source_id=source_id,
                stellar_case_id=str(case.get("_id") or "").strip(),
                middleware_case_id=middleware_case_id,
                jira_key=jira_key,
                customer_code=customer_code,
                decision=decision.to_dict(),
                context=context,
                ai_sections=decision.ai_sections,
                snapshot_id=snapshot_id,
            )
            decision.context_snapshot["decision_event_id"] = event_id
        except Exception as e:
            logger.warning("decision persist failed: %s", e)

    return decision


# Re-export helpers used by runner
__all__ = [
    "DecisionResult",
    "evaluate_case_decision",
    "get_decision_store",
    "apply_decision_to_jira_fields",
    "should_create_ticket",
    "should_notify_customer",
    "should_notify_internal",
    "_decision_enabled",
]
