"""Bridge DecisionResult ↔ SOC notify AI (single LLM call, shared Dataset seed)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import NotifySettings, get_notify_settings
from app.decision.models import DecisionResult
from app.decision.store import DecisionStore

logger = logging.getLogger(__name__)


def brief_decision_for_ai(decision: DecisionResult | dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact machine decision for LLM context (advisory; does not override rules)."""
    if decision is None:
        return None
    if isinstance(decision, DecisionResult):
        d = decision
        return {
            "action": d.action,
            "escalation": d.escalation,
            "playbook_id": d.playbook_id,
            "isolate_host_advisory": bool(d.isolate_host),
            "notify_customer": bool(d.notify_customer),
            "confidence": d.confidence,
            "rule_hits": list(d.rule_hits)[:10],
            "knowledge_hits": list(d.knowledge_hits)[:10],
            "summary": d.summary,
        }
    if isinstance(decision, dict):
        return {
            "action": str(decision.get("action") or ""),
            "escalation": str(decision.get("escalation") or ""),
            "playbook_id": str(decision.get("playbook_id") or ""),
            "isolate_host_advisory": bool(decision.get("isolate_host")),
            "notify_customer": bool(decision.get("notify_customer")),
            "confidence": decision.get("confidence"),
            "rule_hits": list(decision.get("rule_hits") or [])[:10],
            "knowledge_hits": list(decision.get("knowledge_hits") or [])[:10],
            "summary": str(decision.get("summary") or ""),
        }
    return None


def extract_ai_sections_blob(status: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull AI payload from notify_ticket_created status (top-level or email.ai)."""
    if not isinstance(status, dict):
        return None
    if isinstance(status.get("ai"), dict):
        return status["ai"]
    email = status.get("email")
    if isinstance(email, dict) and isinstance(email.get("ai"), dict):
        return email["ai"]
    return None


def normalize_ai_sections(blob: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep only Dataset fields when blob looks successful."""
    if not isinstance(blob, dict):
        return None
    if blob.get("skipped") or blob.get("ok") is False:
        return None
    if not blob.get("ok") and not (
        blob.get("executive_summary") or blob.get("event_description") or blob.get("recommended_actions")
    ):
        return None
    return {
        "executive_summary": blob.get("executive_summary"),
        "event_description": blob.get("event_description"),
        "recommended_actions": blob.get("recommended_actions"),
    }


async def generate_ai_aligned_with_decision(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    middleware_case_id: str = "",
    customer_code: str = "",
    decision: DecisionResult | dict[str, Any] | None = None,
    settings: NotifySettings | None = None,
    precomputed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    One LLM path shared by Decision create + SOC notify.

    If ``precomputed`` already has sections, skip the network call.
    """
    ns = settings or get_notify_settings()
    ready = normalize_ai_sections(precomputed)
    if ready and (ready.get("executive_summary") or ready.get("event_description")):
        return {"ok": True, "source": "precomputed", **ready}

    from app.ai.soc_notify import generate_stellar_soc_ai_sections

    return await generate_stellar_soc_ai_sections(
        case=case,
        bundle=bundle,
        middleware_case_id=middleware_case_id,
        customer_code=customer_code,
        settings=ns,
        decision=brief_decision_for_ai(decision),
    )


def seed_decision_ai(
    store: DecisionStore | None,
    *,
    event_id: str,
    ai_blob: dict[str, Any] | None,
) -> bool:
    """Persist AI sections onto decision_events. Returns True if written."""
    if store is None or not event_id:
        return False
    sections = normalize_ai_sections(ai_blob)
    if not sections:
        return False
    try:
        store.update_ai_sections(event_id, sections)
        return True
    except Exception as e:
        logger.warning("decision AI seed update failed: %s", e)
        return False
