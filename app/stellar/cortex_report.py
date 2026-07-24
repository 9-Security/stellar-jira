"""Fetch and normalize Cortex XDR alert rows from Stellar Cyber Cases API."""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from app.stellar.case_display_name import clean_stellar_case_name
from app.stellar.client import StellarClient
from app.stellar.darktrace_report import (
    _case_matches_tenant_name,
    _date_range_to_ms,
    _in_time_window,
    _ms_to_iso,
    alert_source,
    extract_alert_docs,
)

_CORTEX_CASE_HINTS = ("cortex", "xdr", "palo alto", "paloalto", "wildfire")


def _case_name_suggests_cortex(case_name: str) -> bool:
    lower = str(case_name or "").lower()
    return any(hint in lower for hint in _CORTEX_CASE_HINTS)


def is_cortex_source(src: dict[str, Any], *, case_name: str = "") -> bool:
    """True when alert document _source is from Cortex XDR in Stellar."""
    if isinstance(src.get("palo_alto_networks"), dict):
        return True
    if isinstance(src.get("xdr_event"), dict):
        return True
    cef = src.get("cef")
    if isinstance(cef, dict):
        vendor = str(cef.get("deviceVendor") or cef.get("device_vendor") or "").lower()
        if "palo alto" in vendor or "cortex" in vendor or "xdr" in vendor:
            return True
    for key in ("event_source", "dev_class", "msg_class"):
        val = str(src.get(key) or "").lower()
        if any(h in val for h in ("cortex", "xdr", "palo")):
            return True
    if _case_name_suggests_cortex(case_name):
        return True
    return False


def _pan_dict(src: dict[str, Any]) -> dict[str, Any]:
    pan = src.get("palo_alto_networks")
    return pan if isinstance(pan, dict) else {}


def cortex_alert_display_name(src: dict[str, Any], *, case_name: str = "") -> str:
    pan = _pan_dict(src)
    for key in ("name", "bioc_indicator", "description"):
        val = str(pan.get(key) or "").strip()
        if val and len(val) <= 200:
            return val
    for key in ("name", "display_name", "title", "rule_name"):
        val = str(src.get(key) or "").strip()
        if val:
            return val
    xdr = src.get("xdr_event")
    if isinstance(xdr, dict):
        desc = str(xdr.get("description") or "").strip()
        if desc:
            return clean_stellar_case_name(desc)[:200]
    cleaned = clean_stellar_case_name(case_name)
    return cleaned or "Cortex XDR 事件"


def _response_action_from_src(src: dict[str, Any]) -> str:
    pan = _pan_dict(src)
    for key in ("action_pretty", "action"):
        val = str(pan.get(key) or "").strip()
        if val:
            return val
    for key in ("action_pretty", "response_action", "alert_action"):
        val = str(src.get(key) or "").strip()
        if val:
            return val
    return ""


def _parse_summary_tactics(summary_payload: Any) -> list[str]:
    if not isinstance(summary_payload, dict):
        return []
    data = summary_payload.get("data")
    if not isinstance(data, dict):
        data = summary_payload
    tactics = data.get("tactics")
    if not isinstance(tactics, list):
        return []
    return [str(t).strip() for t in tactics if str(t).strip()]


def _first_host_from_observables(observables_payload: Any) -> tuple[str, str]:
    if not isinstance(observables_payload, dict):
        return "", ""
    obs = observables_payload.get("observables")
    if not isinstance(obs, dict):
        obs = observables_payload.get("data")
        if isinstance(obs, dict):
            obs = obs.get("observables")
    if not isinstance(obs, dict):
        return "", ""
    hosts = obs.get("host")
    if not isinstance(hosts, list):
        return "", ""
    for host in hosts:
        if isinstance(host, dict):
            hostname = str(host.get("hostname") or host.get("name") or "").strip()
            ip = str(host.get("ip") or host.get("address") or "").strip()
            if hostname or ip:
                return hostname, ip
        else:
            text = str(host).strip()
            if text:
                return text, ""
    return "", ""


def normalize_cortex_row(
    *,
    case: dict[str, Any],
    alert_doc: dict[str, Any],
    tz: ZoneInfo | None = None,
    mitre_tactics: list[str] | None = None,
    hostname: str = "",
    hostip: str = "",
) -> dict[str, Any]:
    src = alert_source(alert_doc)
    pan = _pan_dict(src)
    case_name = str(case.get("name") or "")
    write_ms = src.get("write_time") or src.get("timestamp") or alert_doc.get("write_time")
    case_created_raw = case.get("created_at")
    case_created_ms = int(case_created_raw) if case_created_raw is not None else None
    return {
        "case_ticket_id": case.get("ticket_id"),
        "case_id": case.get("_id"),
        "case_name": case_name,
        "case_status": case.get("status"),
        "case_severity": case.get("severity"),
        "case_created_at": _ms_to_iso(case.get("created_at"), tz=tz),
        "case_created_ms": case_created_ms,
        "case_modified_at": _ms_to_iso(case.get("modified_at"), tz=tz),
        "tenant_name": case.get("tenant_name"),
        "assignee_name": case.get("assignee_name") or case.get("assignee"),
        "alert_doc_id": alert_doc.get("_id"),
        "alert_name": cortex_alert_display_name(src, case_name=case_name),
        "alert_category": str(pan.get("category") or "").strip(),
        "response_action": _response_action_from_src(src),
        "cef_severity": (src.get("cef") or {}).get("severity") if isinstance(src.get("cef"), dict) else None,
        "hostname": hostname,
        "hostip": hostip,
        "write_time": _ms_to_iso(write_ms, tz=tz),
        "write_time_ms": int(write_ms) if write_ms is not None else None,
        "mitre_tactics": list(mitre_tactics or []),
    }


async def fetch_cortex_events(
    client: StellarClient,
    *,
    since_date: date | None = None,
    until_date: date | None = None,
    timezone_name: str = "Asia/Taipei",
    page_size: int = 500,
    max_pages: int = 200,
    fetch_alerts_mode: str = "all_cases",
    tenant_name_filter: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return normalized Cortex XDR alert rows and a summary dict."""
    tz = ZoneInfo(timezone_name)
    since_ms, until_ms = _date_range_to_ms(since_date, until_date, tz=tz)
    cases, truncated = await client.list_all_cases(page_size=page_size, max_pages=max_pages)
    rows: list[dict[str, Any]] = []
    cases_scanned = 0
    cases_with_alerts = 0
    alert_errors = 0
    summary_fetch_errors = 0

    for case in cases:
        case_id = str(case.get("_id") or "")
        if not case_id:
            continue
        if not _case_matches_tenant_name(case, tenant_name_filter):
            continue
        case_name = str(case.get("name") or "")
        case_name_lower = case_name.lower()
        if fetch_alerts_mode == "name_or_alerts" and not _case_name_suggests_cortex(case_name):
            continue
        cases_scanned += 1
        try:
            alerts_payload = await client.get_case_alerts(case_id)
        except Exception:
            alert_errors += 1
            continue

        docs = extract_alert_docs(alerts_payload)
        case_created_ms = int(case.get("created_at") or 0) or None
        matched_docs: list[dict[str, Any]] = []
        for doc in docs:
            src = alert_source(doc)
            if not is_cortex_source(src, case_name=case_name):
                continue
            write_ms_raw = src.get("write_time") or src.get("timestamp")
            write_ms = int(write_ms_raw) if write_ms_raw is not None else None
            if not _in_time_window(
                write_ms=write_ms,
                case_created_ms=case_created_ms,
                since_ms=since_ms,
                until_ms=until_ms,
            ):
                continue
            matched_docs.append(doc)

        if not matched_docs:
            continue

        cases_with_alerts += 1
        mitre_tactics: list[str] = []
        hostname = ""
        hostip = ""
        try:
            summary_payload = await client.get_case_summary(case_id)
            mitre_tactics = _parse_summary_tactics(summary_payload)
        except Exception:
            summary_fetch_errors += 1
        try:
            observables_payload = await client.get_case_observables(case_id)
            hostname, hostip = _first_host_from_observables(observables_payload)
        except Exception:
            pass

        for doc in matched_docs:
            rows.append(
                normalize_cortex_row(
                    case=case,
                    alert_doc=doc,
                    tz=tz,
                    mitre_tactics=mitre_tactics,
                    hostname=hostname,
                    hostip=hostip,
                )
            )

    rows.sort(key=lambda r: (r.get("write_time_ms") or 0, str(r.get("case_ticket_id") or "")))
    summary = {
        "total_cases_in_tenant": len(cases),
        "cases_scanned": cases_scanned,
        "cases_with_any_alerts": cases_with_alerts,
        "cortex_event_count": len(rows),
        "cases_truncated": truncated,
        "alert_fetch_errors": alert_errors,
        "summary_fetch_errors": summary_fetch_errors,
        "since_date": since_date.isoformat() if since_date else None,
        "until_date": until_date.isoformat() if until_date else None,
        "timezone": timezone_name,
        "fetch_alerts_mode": fetch_alerts_mode,
        "tenant_name_filter": tenant_name_filter,
    }
    return rows, summary
