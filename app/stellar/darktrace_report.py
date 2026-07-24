"""Fetch and normalize Darktrace alert rows from Stellar Cyber Cases API."""

from __future__ import annotations

import ipaddress
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.stellar.client import StellarClient


def _ms_to_iso(ms: Any, *, tz: ZoneInfo | None = None) -> str:
    try:
        n = int(ms)
    except (TypeError, ValueError):
        return ""
    dt = datetime.fromtimestamp(n / 1000.0, tz=timezone.utc)
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def _date_range_to_ms(
    since: date | None,
    until: date | None,
    *,
    tz: ZoneInfo,
) -> tuple[int | None, int | None]:
    """Inclusive local calendar dates → UTC epoch ms [since, until_end)."""
    since_ms: int | None = None
    until_ms: int | None = None
    if since is not None:
        since_ms = int(datetime.combine(since, time.min, tzinfo=tz).timestamp() * 1000)
    if until is not None:
        until_end = datetime.combine(until, time.max.replace(microsecond=0), tzinfo=tz)
        until_ms = int(until_end.timestamp() * 1000) + 999
    return since_ms, until_ms


def is_darktrace_source(src: dict[str, Any]) -> bool:
    """True when alert document _source is from Darktrace."""
    for key in ("event_source", "dev_class", "msg_class"):
        val = str(src.get(key) or "").strip().lower()
        if val == "darktrace":
            return True
    cef = src.get("cef")
    if isinstance(cef, dict):
        device_vendor = str(cef.get("deviceVendor") or cef.get("device_vendor") or "").lower()
        if "darktrace" in device_vendor:
            return True
    return False


def extract_alert_docs(alerts_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    return [d for d in docs if isinstance(d, dict)]


def alert_source(doc: dict[str, Any]) -> dict[str, Any]:
    src = doc.get("_source")
    return src if isinstance(src, dict) else doc


def alert_display_name(src: dict[str, Any]) -> str:
    cef = src.get("cef")
    if isinstance(cef, dict):
        for key in ("name", "signatureId", "deviceEventClassId"):
            val = cef.get(key)
            if val and str(val).strip():
                return str(val).strip()
    for key in ("name", "display_name", "title"):
        val = src.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _looks_like_ip(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    try:
        ipaddress.ip_address(text.split("/")[0])
        return True
    except ValueError:
        return False


def _extract_host_label(val: Any) -> str:
    """Return a display hostname; never stringify host dicts or use bare IPs."""
    if val is None:
        return ""
    if isinstance(val, dict):
        for key in ("name", "hostname", "host_name", "hostName", "device", "device_name", "deviceName"):
            label = val.get(key)
            if label is None:
                continue
            text = str(label).strip()
            if text and not _looks_like_ip(text):
                return text
        return ""
    if isinstance(val, list):
        for item in val:
            label = _extract_host_label(item)
            if label:
                return label
        return ""
    text = str(val).strip()
    if not text or text[0] in "{[":
        return ""
    if _looks_like_ip(text):
        return ""
    return text


def _extract_host_ip(val: Any) -> str:
    if isinstance(val, dict):
        ip = val.get("ip")
        if ip is not None:
            text = str(ip).strip()
            if text:
                return text
    if isinstance(val, str):
        text = val.strip()
        if text and _looks_like_ip(text):
            return text
    return ""


def alert_hostname(src: dict[str, Any]) -> str:
    for key in ("hostname", "host_name", "hostip_host", "src_host", "dest_host", "host"):
        label = _extract_host_label(src.get(key))
        if label:
            return label
    cef = src.get("cef")
    if isinstance(cef, dict):
        for key in ("deviceHostName", "device_hostname"):
            label = _extract_host_label(cef.get(key))
            if label:
                return label
    dt = src.get("darktrace")
    if isinstance(dt, dict):
        for key in ("hostname", "device", "devicehostname"):
            label = _extract_host_label(dt.get(key))
            if label:
                return label
    return ""


def _raw_host_fallback(src: dict[str, Any]) -> str:
    """Use Stellar raw host fields when no hostname/FQDN is available."""
    for key in ("hostip_host", "hostip", "srcip"):
        val = src.get(key)
        if val is not None:
            text = str(val).strip()
            if text:
                return text
    host_val = src.get("host")
    if isinstance(host_val, dict):
        ip = host_val.get("ip")
        if ip is not None:
            text = str(ip).strip()
            if text:
                return text
    return ""


def alert_hostname_or_raw(src: dict[str, Any]) -> str:
    hostname = alert_hostname(src)
    if hostname:
        return hostname
    return _raw_host_fallback(src)


def alert_hostip(src: dict[str, Any]) -> str:
    for key in ("hostip", "srcip", "destip"):
        val = src.get(key)
        if val is not None:
            text = str(val).strip()
            if text:
                return text
    for key in ("host", "src_host", "dest_host"):
        ip = _extract_host_ip(src.get(key))
        if ip:
            return ip
    return ""


def normalize_darktrace_row(
    *,
    case: dict[str, Any],
    alert_doc: dict[str, Any],
    tz: ZoneInfo | None = None,
) -> dict[str, Any]:
    src = alert_source(alert_doc)
    dt = src.get("darktrace") if isinstance(src.get("darktrace"), dict) else {}
    cef = src.get("cef") if isinstance(src.get("cef"), dict) else {}
    write_ms = src.get("write_time") or src.get("timestamp") or alert_doc.get("write_time")
    return {
        "case_ticket_id": case.get("ticket_id"),
        "case_id": case.get("_id"),
        "case_name": case.get("name"),
        "case_status": case.get("status"),
        "case_severity": case.get("severity"),
        "case_created_at": _ms_to_iso(case.get("created_at"), tz=tz),
        "case_modified_at": _ms_to_iso(case.get("modified_at"), tz=tz),
        "tenant_name": case.get("tenant_name"),
        "assignee_name": case.get("assignee_name") or case.get("assignee"),
        "alert_doc_id": alert_doc.get("_id"),
        "anomaly_id": src.get("anomaly_id") or src.get("orig_id"),
        "alert_name": alert_display_name(src),
        "cef_severity": cef.get("severity"),
        "event_score": src.get("event_score"),
        "event_source": src.get("event_source"),
        "dev_class": src.get("dev_class"),
        "msg_class": src.get("msg_class"),
        "hostip": alert_hostip(src),
        "hostip_host": str(src.get("hostip_host") or "").strip(),
        "hostname": alert_hostname_or_raw(src),
        "write_time": _ms_to_iso(write_ms, tz=tz),
        "write_time_ms": int(write_ms) if write_ms is not None else None,
        "darktrace_external_id": dt.get("externalid") or dt.get("external_id"),
        "darktrace_mitre_id": dt.get("mitreid") or dt.get("mitre_id"),
        "darktrace_url": dt.get("darktraceurl") or dt.get("darktrace_url"),
    }


def _in_time_window(
    *,
    write_ms: int | None,
    case_created_ms: int | None,
    since_ms: int | None,
    until_ms: int | None,
) -> bool:
    if since_ms is None and until_ms is None:
        return True
    ref = write_ms if write_ms is not None else case_created_ms
    if ref is None:
        return True
    if since_ms is not None and ref < since_ms:
        return False
    if until_ms is not None and ref > until_ms:
        return False
    return True


def _case_matches_tenant_name(case: dict[str, Any], tenant_name_filter: str | None) -> bool:
    if not tenant_name_filter or not str(tenant_name_filter).strip():
        return True
    needle = str(tenant_name_filter).strip().lower()
    tn = str(case.get("tenant_name") or "").strip().lower()
    return tn == needle


async def fetch_darktrace_events(
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
    """
    Return normalized Darktrace alert rows and a summary dict.

    ``fetch_alerts_mode``:
    - ``all_cases``: GET alerts for every case (complete; more API calls)
    - ``name_or_alerts``: only cases whose name contains "darktrace" (faster heuristic)
    """
    tz = ZoneInfo(timezone_name)
    since_ms, until_ms = _date_range_to_ms(since_date, until_date, tz=tz)
    cases, truncated = await client.list_all_cases(page_size=page_size, max_pages=max_pages)
    rows: list[dict[str, Any]] = []
    cases_scanned = 0
    cases_with_alerts = 0
    alert_errors = 0

    for case in cases:
        case_id = str(case.get("_id") or "")
        if not case_id:
            continue
        if not _case_matches_tenant_name(case, tenant_name_filter):
            continue
        case_name_lower = str(case.get("name") or "").lower()
        if fetch_alerts_mode == "name_or_alerts" and "darktrace" not in case_name_lower:
            continue
        cases_scanned += 1
        try:
            alerts_payload = await client.get_case_alerts(case_id)
        except Exception:
            alert_errors += 1
            continue
        docs = extract_alert_docs(alerts_payload)
        if docs:
            cases_with_alerts += 1
        case_created_ms = int(case.get("created_at") or 0) or None
        for doc in docs:
            src = alert_source(doc)
            if not is_darktrace_source(src):
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
            rows.append(normalize_darktrace_row(case=case, alert_doc=doc, tz=tz))

    rows.sort(key=lambda r: (r.get("write_time_ms") or 0, str(r.get("case_ticket_id") or "")))
    summary = {
        "total_cases_in_tenant": len(cases),
        "cases_scanned": cases_scanned,
        "cases_with_any_alerts": cases_with_alerts,
        "darktrace_event_count": len(rows),
        "cases_truncated": truncated,
        "alert_fetch_errors": alert_errors,
        "since_date": since_date.isoformat() if since_date else None,
        "until_date": until_date.isoformat() if until_date else None,
        "timezone": timezone_name,
        "fetch_alerts_mode": fetch_alerts_mode,
        "tenant_name_filter": tenant_name_filter,
    }
    return rows, summary
