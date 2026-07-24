"""Compact Stellar case context for SOC notify LLM prompts."""

from __future__ import annotations

import json
from typing import Any

from app.stellar.alert_fields import stellar_primary_file_path
from app.stellar.case_display_name import stellar_case_display_name
from app.stellar.cortex_fields import cortex_case_id_from_alert_source
from app.stellar.response_action import (
    _response_action_from_alert_source,
    stellar_notify_disposition_label,
    stellar_response_action_is_blocked,
    stellar_response_action_text,
)

# Prefer fewer, high-signal alerts in the LLM payload (list is sorted; prompt uses top 1–3).
_AI_ALERT_LIMIT = 12
# Causal / agentic packs: keep every alert, but strip nested noise.
_CAUSAL_ALERT_LIMIT = 80
_CAUSAL_DESC_LEN = 500


def _alert_docs(bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    alerts_payload = (bundle or {}).get("alerts")
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    out: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        if isinstance(src, dict):
            out.append(src)
    return out


def _pan(src: dict[str, Any]) -> dict[str, Any]:
    pan = src.get("palo_alto_networks")
    return pan if isinstance(pan, dict) else {}


def _cortex_case_id(src: dict[str, Any]) -> str:
    """Cortex XDR case id on the alert (often missing on BIOC-only / Stellar-elevated rows)."""
    return cortex_case_id_from_alert_source(src)

def _is_malware_signal(src: dict[str, Any]) -> bool:
    pan = _pan(src)
    if str(pan.get("category") or "").strip().lower() == "malware":
        return True
    name = str(pan.get("name") or "").lower()
    if "wildfire" in name or "malware" in name:
        return True
    xdr = src.get("xdr_event")
    if isinstance(xdr, dict):
        blob = f"{xdr.get('display_name') or ''} {xdr.get('description') or ''}".lower()
        if "wildfire" in blob or "malware" in blob:
            return True
    return False


def _alert_ai_sort_key(src: dict[str, Any]) -> tuple[int, int, int, int, str]:
    """
    Lower tuple = higher relevance for LLM context.

    Order: blocked/prevented → malware/WildFire → has Cortex case_id → category.
    """
    action = _response_action_from_alert_source(src)
    blocked = 0 if stellar_response_action_is_blocked(action) else 1
    malware = 0 if _is_malware_signal(src) else 1
    cortex = 0 if _cortex_case_id(src) else 1
    cat = str(_pan(src).get("category") or "").strip().lower()
    cat_rank = {
        "malware": 0,
        "exploit": 1,
        "command and control": 2,
        "lateral movement": 3,
        "exfiltration": 4,
        "persistence": 5,
        "execution": 6,
        "privilege escalation": 7,
    }.get(cat, 8)
    return (blocked, malware, cortex, cat_rank, action)


def _brief_alerts(bundle: dict[str, Any] | None, *, limit: int = _AI_ALERT_LIMIT) -> list[dict[str, str]]:
    docs = sorted(_alert_docs(bundle), key=_alert_ai_sort_key)
    rows: list[dict[str, str]] = []
    for src in docs[:limit]:
        pan = _pan(src)
        xdr = src.get("xdr_event") if isinstance(src.get("xdr_event"), dict) else {}
        action = _response_action_from_alert_source(src)
        rows.append(
            {
                "category": str(pan.get("category") or "").strip(),
                "action": action,
                "cortex_case_id": _cortex_case_id(src),
                "description": str(pan.get("description") or "")[:280],
                "xdr": str(xdr.get("description") or "")[:280],
            }
        )
    return rows


def _host_from_src(src: dict[str, Any]) -> tuple[str, str]:
    host = src.get("host") if isinstance(src.get("host"), dict) else {}
    name = str(host.get("name") or host.get("hostname") or src.get("agent_hostname") or "").strip()
    ip = ""
    hip = host.get("ip")
    if isinstance(hip, list) and hip:
        ip = str(hip[0] or "").strip()
    elif hip:
        ip = str(hip).strip()
    pan = _pan(src)
    if not name:
        name = str(pan.get("agent_fqdn") or "").strip()
    return name, ip


def _first_event(src: dict[str, Any]) -> dict[str, Any]:
    pan = _pan(src)
    events = pan.get("events")
    if isinstance(events, list) and events and isinstance(events[0], dict):
        return events[0]
    return {}


def _causal_alert_row(src: dict[str, Any]) -> dict[str, Any]:
    pan = _pan(src)
    ev = _first_event(src)
    host_name, host_ip = _host_from_src(src)
    ts = str(src.get("timestamp_utc") or src.get("timestamp") or "").strip()
    if not ts and pan.get("detection_timestamp") is not None:
        ts = str(pan.get("detection_timestamp"))
    desc = str(pan.get("description") or "").strip()
    if not desc:
        xdr = src.get("xdr_event") if isinstance(src.get("xdr_event"), dict) else {}
        desc = str(xdr.get("description") or "").strip()
    return {
        "t": ts,
        "host": host_name,
        "host_ip": host_ip,
        "user": str(ev.get("user_name") or pan.get("user_name") or "").strip(),
        "category": str(pan.get("category") or "").strip(),
        "name": str(pan.get("name") or "").strip(),
        "action": _response_action_from_alert_source(src),
        "cortex_case_id": _cortex_case_id(src),
        "alert_id": str(pan.get("alert_id") or "").strip(),
        "process": str(
            ev.get("actor_process_image_name") or ev.get("causality_actor_process_image_name") or ""
        ).strip(),
        "process_path": str(
            ev.get("actor_process_image_path") or ev.get("causality_actor_process_image_path") or ""
        ).strip(),
        "cmdline": str(ev.get("actor_process_command_line") or "")[:320].strip(),
        "parent": str(ev.get("os_actor_process_image_name") or "").strip(),
        "description": desc[:_CAUSAL_DESC_LEN],
    }


def _causal_alerts(bundle: dict[str, Any] | None, *, limit: int = _CAUSAL_ALERT_LIMIT) -> list[dict[str, Any]]:
    docs = _alert_docs(bundle)

    def _ts_key(src: dict[str, Any]) -> tuple:
        pan = _pan(src)
        ts = src.get("timestamp_utc") or src.get("timestamp") or pan.get("detection_timestamp") or 0
        return (str(ts),) + _alert_ai_sort_key(src)

    rows = [_causal_alert_row(src) for src in sorted(docs, key=_ts_key)]
    return rows[:limit]


def build_stellar_causal_ai_context(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    middleware_case_id: str = "",
    customer_code: str = "",
    decision: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """All-alert compact pack for causal reconstruction (fits agent window better than raw export)."""
    alerts = _causal_alerts(bundle)
    out: dict[str, Any] = {
        "middleware_case_id": str(middleware_case_id or "").strip(),
        "customer_code": str(customer_code or "").strip().upper(),
        "stellar_case_id": str(case.get("_id") or (bundle or {}).get("case_id") or "").strip(),
        "ticket_id": case.get("ticket_id"),
        "display_name": stellar_case_display_name(case, bundle),
        "severity": str(case.get("severity") or "").strip(),
        "status": str(case.get("status") or "").strip(),
        "score": case.get("score"),
        "alert_count": case.get("size") or len(alerts),
        "response_action": stellar_response_action_text(bundle),
        "disposition": stellar_notify_disposition_label(bundle),
        "primary_file_path": stellar_primary_file_path(bundle),
        "summary": _summary_block(bundle),
        "observables": _observables_block(bundle),
        "alerts_note": (
            "ALL alerts compacted for causal analysis (time-sorted). "
            "Each row has host/user/process/path/action. "
            "disposition is case-level rollup (any Prevented → 已阻擋)."
        ),
        "alerts": alerts,
    }
    if isinstance(meta, dict) and meta:
        if meta.get("decision_preview"):
            out["decision_preview"] = meta["decision_preview"]
        if meta.get("action_histogram") is not None:
            out["action_histogram"] = meta["action_histogram"]
        if meta.get("has_cortex_case_id") is not None:
            out["has_cortex_case_id"] = meta["has_cortex_case_id"]
    if isinstance(decision, dict) and decision:
        out["decision"] = decision
    return out


def stellar_causal_ai_context_json(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    middleware_case_id: str = "",
    customer_code: str = "",
    decision: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    ctx = build_stellar_causal_ai_context(
        case=case,
        bundle=bundle,
        middleware_case_id=middleware_case_id,
        customer_code=customer_code,
        decision=decision,
        meta=meta,
    )
    return json.dumps(ctx, ensure_ascii=False, indent=2)


def _summary_block(bundle: dict[str, Any] | None) -> dict[str, Any]:
    summary_data = (bundle or {}).get("summary")
    if not isinstance(summary_data, dict):
        return {}
    inner = summary_data.get("data")
    if not isinstance(inner, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("tactics", "techniques", "stages"):
        val = inner.get(key)
        if val:
            out[key] = val
    return out


def _observables_block(bundle: dict[str, Any] | None) -> dict[str, Any]:
    obs_payload = (bundle or {}).get("observables")
    if not isinstance(obs_payload, dict):
        return {}
    obs = obs_payload.get("observables")
    return obs if isinstance(obs, dict) else {}


def build_stellar_soc_ai_context(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    middleware_case_id: str = "",
    customer_code: str = "",
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured facts for the LLM (no secrets beyond alert content)."""
    alerts = _brief_alerts(bundle)
    out: dict[str, Any] = {
        "middleware_case_id": str(middleware_case_id or "").strip(),
        "customer_code": str(customer_code or "").strip().upper(),
        "stellar_case_id": str(case.get("_id") or (bundle or {}).get("case_id") or "").strip(),
        "ticket_id": case.get("ticket_id"),
        "tenant_name": str(case.get("tenant_name") or "").strip(),
        "display_name": stellar_case_display_name(case, bundle),
        "severity": str(case.get("severity") or "").strip(),
        "status": str(case.get("status") or "").strip(),
        "score": case.get("score"),
        "alert_count": case.get("size"),
        "response_action": stellar_response_action_text(bundle),
        "disposition": stellar_notify_disposition_label(bundle),
        "primary_file_path": stellar_primary_file_path(bundle),
        "summary": _summary_block(bundle),
        "observables": _observables_block(bundle),
        "alerts_sort": (
            "relevance: blocked/prevented first, then malware/WildFire, "
            "then alerts with cortex_case_id; prefer narrating from the first 1–3 alerts"
        ),
        "alerts": alerts,
    }
    if isinstance(decision, dict) and decision:
        out["decision"] = decision
    return out


def stellar_soc_ai_context_json(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    middleware_case_id: str = "",
    customer_code: str = "",
    decision: dict[str, Any] | None = None,
) -> str:
    ctx = build_stellar_soc_ai_context(
        case=case,
        bundle=bundle,
        middleware_case_id=middleware_case_id,
        customer_code=customer_code,
        decision=decision,
    )
    return json.dumps(ctx, ensure_ascii=False, indent=2)
