"""Deterministic security decision rules (versionable JSON playbooks)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.decision.models import DecisionResult
from app.stellar.severity_filter import normalize_stellar_severity
from app.stellar.response_action import (
    stellar_notify_disposition_label,
    stellar_response_action_is_blocked,
    stellar_response_action_text,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES_PATH = REPO_ROOT / "config" / "decision_rules.json"


def load_decision_rules(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_RULES_PATH
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.is_file():
        logger.warning("decision rules not found at %s — using built-in defaults", p)
        return _builtin_rules()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("failed to load decision rules %s: %s — using defaults", p, e)
        return _builtin_rules()
    if not isinstance(data, dict):
        return _builtin_rules()
    return data


def _builtin_rules() -> dict[str, Any]:
    return {
        "version": "builtin-1",
        "defaults": {
            "action": "create_ticket",
            "escalation": "L1",
            "notify_customer": False,
            "notify_internal": True,
            "isolate_host": False,
            "playbook_id": "PB-DEFAULT",
            "confidence": 0.4,
            "jira_priority": None,
        },
        "rules": [
            {
                "id": "sev_low_defer",
                "priority": 10,
                "when": {"severity_in": ["Low"]},
                "then": {
                    "action": "defer",
                    "escalation": "L1",
                    "notify_internal": False,
                    "notify_customer": False,
                    "playbook_id": "PB-DEFER-LOW",
                    "confidence": 0.85,
                    "summary": "Low severity — defer ticket create until severity rises",
                },
            },
            {
                "id": "sev_medium_l1",
                "priority": 20,
                "when": {"severity_in": ["Medium"]},
                "then": {
                    "action": "create_ticket",
                    "escalation": "L1",
                    "notify_customer": False,
                    "playbook_id": "PB-L1-MED",
                    "confidence": 0.7,
                    "jira_priority": "Medium",
                    "jira_labels": ["decision-l1"],
                    "summary": "Medium severity — L1 investigate first",
                },
            },
            {
                "id": "malware_critical_ir",
                "priority": 100,
                "when": {
                    "severity_in": ["Critical", "High"],
                    "alert_category_any": ["malware"],
                    "name_contains_any": ["wildfire", "malware"],
                },
                "match": "any_extra",
                "then": {
                    "action": "escalate",
                    "escalation": "IR",
                    "notify_customer": True,
                    "notify_internal": True,
                    "isolate_host": True,
                    "playbook_id": "PB-IR-MALWARE",
                    "confidence": 0.9,
                    "jira_priority": "Highest",
                    "jira_labels": ["decision-ir", "malware"],
                    "summary": "Malware/WildFire signals — escalate to IR (isolation advisory)",
                },
            },
            {
                "id": "critical_high_l2",
                "priority": 50,
                "when": {"severity_in": ["Critical", "High"]},
                "then": {
                    "action": "create_ticket",
                    "escalation": "L2",
                    "notify_customer": True,
                    "playbook_id": "PB-L2-HIGH",
                    "confidence": 0.75,
                    "jira_priority": "High",
                    "jira_labels": ["decision-l2"],
                    "summary": "High/Critical — L2 triage + customer notify",
                },
            },
            {
                "id": "already_blocked_review",
                "priority": 80,
                "when": {
                    "severity_in": ["Critical", "High", "Medium"],
                    "disposition": "已阻擋",
                },
                "then": {
                    "action": "create_ticket",
                    "escalation": "L2",
                    "notify_customer": True,
                    "isolate_host": False,
                    "playbook_id": "PB-L2-BLOCKED",
                    "confidence": 0.8,
                    "jira_labels": ["decision-blocked-review"],
                    "summary": "Platform already blocked — review efficacy, do not re-isolate",
                },
            },
        ],
    }


def _alert_categories(bundle: dict[str, Any] | None) -> list[str]:
    alerts_payload = (bundle or {}).get("alerts")
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    cats: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        if not isinstance(src, dict):
            continue
        pan = src.get("palo_alto_networks")
        if isinstance(pan, dict):
            cat = str(pan.get("category") or "").strip().lower()
            if cat:
                cats.append(cat)
            name = str(pan.get("name") or "").strip().lower()
            if name:
                cats.append(name)
        name = str(src.get("name") or src.get("display_name") or "").strip().lower()
        if name:
            cats.append(name)
    return cats


def _case_name_blob(case: dict[str, Any], bundle: dict[str, Any] | None) -> str:
    parts = [
        str(case.get("name") or ""),
        str(case.get("display_name") or ""),
    ]
    for cat in _alert_categories(bundle):
        parts.append(cat)
    return " ".join(parts).lower()


def _tactic_names(bundle: dict[str, Any] | None) -> list[str]:
    summary_data = (bundle or {}).get("summary")
    if not isinstance(summary_data, dict):
        return []
    inner = summary_data.get("data")
    if not isinstance(inner, dict):
        return []
    tactics = inner.get("tactics")
    if not isinstance(tactics, list):
        return []
    return [str(t).strip().lower() for t in tactics if str(t).strip()]


def _rule_matches(
    when: dict[str, Any],
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    customer_code: str,
    asset_criticality: str,
    match_mode: str = "all",
) -> bool:
    if not when:
        return True
    severity = normalize_stellar_severity(case.get("severity"))
    disposition = stellar_notify_disposition_label(bundle)
    action_text = stellar_response_action_text(bundle)
    blocked = stellar_response_action_is_blocked(action_text)
    name_blob = _case_name_blob(case, bundle)
    cats = _alert_categories(bundle)
    tactics = _tactic_names(bundle)
    cc = customer_code.strip().upper()

    checks: list[bool] = []

    if "severity_in" in when:
        allowed = {normalize_stellar_severity(x) for x in (when.get("severity_in") or [])}
        checks.append(severity in allowed)

    if "severity_not_in" in when:
        blocked_sev = {normalize_stellar_severity(x) for x in (when.get("severity_not_in") or [])}
        checks.append(severity not in blocked_sev)

    if "disposition" in when:
        checks.append(disposition == str(when["disposition"]))

    if "disposition_in" in when:
        checks.append(disposition in {str(x) for x in (when.get("disposition_in") or [])})

    if "blocked" in when:
        checks.append(blocked is bool(when["blocked"]))

    if "customer_code_in" in when:
        codes = {str(x).strip().upper() for x in (when.get("customer_code_in") or [])}
        checks.append(cc in codes)

    if "asset_criticality_in" in when:
        allowed_ac = {str(x).strip().lower() for x in (when.get("asset_criticality_in") or [])}
        checks.append(asset_criticality.strip().lower() in allowed_ac)

    if "alert_category_any" in when:
        needles = [str(x).strip().lower() for x in (when.get("alert_category_any") or [])]
        checks.append(any(n in cats or any(n in c for c in cats) for n in needles))

    if "name_contains_any" in when:
        needles = [str(x).strip().lower() for x in (when.get("name_contains_any") or [])]
        checks.append(any(n in name_blob for n in needles if n))

    if "mitre_tactic_any" in when:
        needles = [str(x).strip().lower() for x in (when.get("mitre_tactic_any") or [])]
        checks.append(any(n in tactics or any(n in t for t in tactics) for n in needles))

    if "name_regex" in when:
        try:
            checks.append(bool(re.search(str(when["name_regex"]), name_blob, re.I)))
        except re.error:
            checks.append(False)

    if not checks:
        return True
    if match_mode == "any":
        return any(checks)
    if match_mode == "any_extra":
        # Base gates (severity / customer / asset) must all pass;
        # at least one signal gate must also pass.
        base_ok = True
        if "severity_in" in when:
            allowed = {normalize_stellar_severity(x) for x in (when.get("severity_in") or [])}
            base_ok = base_ok and severity in allowed
        if "severity_not_in" in when:
            blocked_sev = {normalize_stellar_severity(x) for x in (when.get("severity_not_in") or [])}
            base_ok = base_ok and severity not in blocked_sev
        if "customer_code_in" in when:
            codes = {str(x).strip().upper() for x in (when.get("customer_code_in") or [])}
            base_ok = base_ok and cc in codes
        if "asset_criticality_in" in when:
            allowed_ac = {str(x).strip().lower() for x in (when.get("asset_criticality_in") or [])}
            base_ok = base_ok and asset_criticality.strip().lower() in allowed_ac
        signal_keys = (
            "alert_category_any",
            "name_contains_any",
            "mitre_tactic_any",
            "name_regex",
            "disposition",
            "disposition_in",
            "blocked",
        )
        has_signal_clause = any(k in when for k in signal_keys)
        if not has_signal_clause:
            return base_ok
        signal_ok = False
        for key in signal_keys:
            if key not in when:
                continue
            if _rule_matches(
                {key: when[key]},
                case=case,
                bundle=bundle,
                customer_code=customer_code,
                asset_criticality=asset_criticality,
                match_mode="all",
            ):
                signal_ok = True
                break
        return base_ok and signal_ok
    return all(checks)


def apply_rules(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    customer_code: str = "",
    asset_criticality: str = "medium",
    rules_doc: dict[str, Any] | None = None,
) -> DecisionResult:
    """Evaluate rules highest-priority first; return merged DecisionResult."""
    doc = rules_doc or load_decision_rules()
    defaults = dict(doc.get("defaults") or {})
    rules = list(doc.get("rules") or [])
    rules.sort(key=lambda r: int((r or {}).get("priority") or 0), reverse=True)

    result = DecisionResult(
        action=str(defaults.get("action") or "create_ticket"),  # type: ignore[arg-type]
        escalation=str(defaults.get("escalation") or "L1"),  # type: ignore[arg-type]
        notify_customer=bool(defaults.get("notify_customer")),
        notify_internal=bool(defaults.get("notify_internal", True)),
        isolate_host=bool(defaults.get("isolate_host")),
        playbook_id=str(defaults.get("playbook_id") or "PB-DEFAULT"),
        confidence=float(defaults.get("confidence") or 0.4),
        jira_priority=(str(defaults["jira_priority"]) if defaults.get("jira_priority") else None),
        jira_labels=list(defaults.get("jira_labels") or []),
        summary=str(defaults.get("summary") or "default decision"),
    )
    # Fix invalid defaults
    if result.action not in ("create_ticket", "defer", "suppress", "escalate"):
        result.action = "create_ticket"
    if result.escalation not in ("L1", "L2", "IR"):
        result.escalation = "L1"

    hits: list[str] = []
    for raw in rules:
        if not isinstance(raw, dict):
            continue
        rid = str(raw.get("id") or "").strip() or "unnamed"
        when = raw.get("when") if isinstance(raw.get("when"), dict) else {}
        match_mode = str(raw.get("match") or "all")
        if not _rule_matches(
            when,
            case=case,
            bundle=bundle,
            customer_code=customer_code,
            asset_criticality=asset_criticality,
            match_mode=match_mode,
        ):
            continue
        then = raw.get("then") if isinstance(raw.get("then"), dict) else {}
        hits.append(rid)
        # First (highest priority) match wins for action/escalation; merge labels
        action = str(then.get("action") or result.action)
        if action in ("create_ticket", "defer", "suppress", "escalate"):
            result.action = action  # type: ignore[assignment]
        esc = str(then.get("escalation") or result.escalation)
        if esc in ("L1", "L2", "IR"):
            result.escalation = esc  # type: ignore[assignment]
        if "notify_customer" in then:
            result.notify_customer = bool(then["notify_customer"])
        if "notify_internal" in then:
            result.notify_internal = bool(then["notify_internal"])
        if "isolate_host" in then:
            result.isolate_host = bool(then["isolate_host"])
        if then.get("playbook_id"):
            result.playbook_id = str(then["playbook_id"])
        if then.get("confidence") is not None:
            try:
                result.confidence = max(0.0, min(1.0, float(then["confidence"])))
            except (TypeError, ValueError):
                pass
        if then.get("jira_priority"):
            result.jira_priority = str(then["jira_priority"])
        for label in then.get("jira_labels") or []:
            s = str(label).strip()
            if s and s not in result.jira_labels:
                result.jira_labels.append(s)
        if then.get("summary"):
            result.summary = str(then["summary"])
        break  # highest-priority match only

    result.rule_hits = hits
    return result
