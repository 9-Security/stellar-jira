"""Map XCockpit / CyCraft payloads into Stellar XDR-friendly JSON."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

REASON_LABELS: dict[int, str] = {
    5: "Suspicious Identity Activity",
    6: "Suspicious Activity",
    7: "Attacker Activity",
    8: "Web Attack",
    9: "Malware",
    10: "Suspicious Process",
    11: "Ransomware",
    12: "CyberDrill",
}


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)):
            return str(value)
    return None


def _first_ip(payload: dict[str, Any]) -> str | None:
    for key in ("IPAddress", "ip", "src_ip", "source_ip"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coerce_timestamp(raw: Any) -> str:
    if raw is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reason_label(raw: Any) -> str | None:
    if raw is None:
        return None
    try:
        return REASON_LABELS.get(int(raw))
    except (TypeError, ValueError):
        return str(raw)


def _malware_info(malwares: Any) -> tuple[str | None, str | None]:
    if not isinstance(malwares, list) or not malwares:
        return None, None
    first = malwares[0]
    if isinstance(first, dict):
        return _first_str(first, "MD5", "FileHash", "hash"), _first_str(
            first, "FileName", "file_name", "path"
        )
    if isinstance(first, str):
        return None, first
    return None, None


def _parse_threat_score(severity: Any) -> int | None:
    if severity is None:
        return None
    try:
        score = int(float(str(severity)))
        if 1 <= score <= 10:
            return score
    except (TypeError, ValueError):
        pass
    label = str(severity).lower()
    for name, value in (
        ("critical", 10),
        ("high", 8),
        ("medium", 5),
        ("low", 3),
        ("unknown", 1),
    ):
        if name in label:
            return value
    return None


def _first_ipv4(values: Any) -> str | None:
    if not isinstance(values, list):
        return None
    for item in values:
        text = str(item).strip()
        parts = text.split(".")
        if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
            return text
    return None


def _apply_stellar_maltrace_aliases(event: dict[str, Any]) -> dict[str, Any]:
    """Map custom XCockpit fields to Stellar maltrace default grid columns."""
    out = dict(event)

    src_ip = out.get("src_ip") or out.get("srcip")
    hostname = out.get("hostname") or out.get("host")
    alert_name = out.get("alert_name")
    severity = out.get("severity")

    if src_ip:
        out.setdefault("srcip", src_ip)
    if hostname:
        out.setdefault("host", hostname)
        out.setdefault("srcip_host", hostname)
    if alert_name:
        out.setdefault("signature", alert_name)
        out.setdefault("msg", out.get("description") or alert_name)
    score = _parse_threat_score(severity)
    if score is not None:
        out["threat_score"] = score

    if "dstip" not in out:
        dst = _first_ipv4(out.get("c2_list"))
        if dst:
            out["dstip"] = dst

    out.setdefault("handler", str(out.get("vendor") or "CyCraft"))
    return {k: v for k, v in out.items() if v is not None}


def event_for_stellar_ingest(event: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky debug fields before POST to Stellar XDR webhook."""
    return {k: v for k, v in event.items() if k != "raw"}


def _stable_fallback_event_id(base: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(base, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"cycraft-{digest}"


def normalize_edr_alert_report(
    report: dict[str, Any],
    *,
    vendor: str,
    source: str,
) -> list[dict[str, Any]]:
    """Flatten XCockpit EDR Alert API (CYCRAFT_E) into Stellar events."""
    report_id = _first_str(report, "ReportID", "ReportId", "id") or "unknown"
    report_time = report.get("ReportTime") or report.get("DateEnd")
    summary = report.get("Summary") if isinstance(report.get("Summary"), dict) else {}
    report_severity = _first_str(summary, "ReportSeverity", "severity") or "unknown"
    customer = _first_str(report, "CustomerName", "customer_name")

    events: list[dict[str, Any]] = []
    campaigns = report.get("Campaigns")
    if not isinstance(campaigns, list):
        campaigns = []

    for campaign in campaigns:
        if not isinstance(campaign, dict):
            continue
        table = campaign.get("EndpointSummaryTable")
        if not isinstance(table, list):
            continue
        for row in table:
            if not isinstance(row, dict):
                continue
            computer_id = _first_str(row, "ComputerID", "computer_id") or "endpoint"
            event_id = f"edr-{report_id}-{computer_id}"
            md5, malware_path = _malware_info(row.get("Malwares"))
            reason = _reason_label(row.get("Reason"))
            c2s = row.get("C2s") if isinstance(row.get("C2s"), list) else []
            threats = row.get("ThreatActivitys") if isinstance(row.get("ThreatActivitys"), list) else []

            event: dict[str, Any] = {
                "vendor": vendor,
                "source": source,
                "event_id": event_id,
                "event_time": _coerce_timestamp(
                    row.get("EventLastSeen") or row.get("EventFirstSeen") or report_time
                ),
                "severity": _first_str(row, "Severity") or report_severity,
                "alert_name": reason or "CyCraft EDR Alert",
                "alert_type": "CYCRAFT_E",
                "report_id": report_id,
                "hostname": _first_str(row, "ComputerName", "computer_name"),
                "computer_id": computer_id,
                "src_ip": _first_ip(row),
                "os": _first_str(row, "Os", "os"),
                "group_name": _first_str(row, "GroupName", "group"),
                "customer_name": customer,
                "file_hash": md5,
                "process_name": malware_path or (threats[0] if threats else None),
                "c2_list": c2s or None,
                "threat_activities": threats or None,
            }
            event = {k: v for k, v in event.items() if v is not None}
            events.append(_apply_stellar_maltrace_aliases(event))

    if not events:
        events.append(
            normalize_cycraft_event(report, vendor=vendor, source=source)
        )
    return events


def normalize_csr_report(
    report: dict[str, Any],
    *,
    vendor: str,
    source: str,
) -> list[dict[str, Any]]:
    """Flatten XCockpit Cyber Situation Report (CYCRAFT_C) into Stellar events."""
    report_id = _first_str(report, "ReportID", "ReportId", "id") or "unknown"
    report_time = report.get("ReportTime") or report.get("DateEnd")
    summary = report.get("Summary") if isinstance(report.get("Summary"), dict) else {}
    report_severity = summary.get("Severity") or summary.get("severity") or "unknown"
    customer = _first_str(summary, "Customer", "customer_name")

    events: list[dict[str, Any]] = []
    endpoints = report.get("Endpoints")
    if not isinstance(endpoints, list):
        endpoints = []

    for row in endpoints:
        if not isinstance(row, dict):
            continue
        entity_id = _first_str(row, "EntityId", "entity_id") or "endpoint"
        files = row.get("Files") if isinstance(row.get("Files"), list) else []
        networks = row.get("Networks") if isinstance(row.get("Networks"), list) else []
        event: dict[str, Any] = {
            "vendor": vendor,
            "source": source,
            "event_id": f"csr-{report_id}-{entity_id}",
            "event_time": _coerce_timestamp(
                summary.get("LastEventTime") or report_time
            ),
            "severity": _first_str(row, "Severity", "severity") or str(report_severity),
            "alert_name": "CyCraft Cyber Situation Report",
            "alert_type": "CYCRAFT_C",
            "report_id": report_id,
            "hostname": _first_str(row, "Name", "name"),
            "computer_id": entity_id,
            "src_ip": _first_ip(row) or (_first_ipv4(row.get("IPAddress"))),
            "os": _first_str(row, "OS", "os"),
            "group_name": _first_str(row, "Group", "group"),
            "customer_name": customer,
            "process_name": str(files[0]) if files else None,
            "c2_list": networks or None,
            "suspicious_file_count": summary.get("SuspiciousFiles"),
            "suspicious_endpoint_count": summary.get("SuspiciousEndpoints"),
        }
        event = {k: v for k, v in event.items() if v is not None}
        events.append(_apply_stellar_maltrace_aliases(event))

    if not events:
        event = {
            "vendor": vendor,
            "source": source,
            "event_id": f"csr-{report_id}-summary",
            "event_time": _coerce_timestamp(summary.get("LastEventTime") or report_time),
            "severity": str(report_severity),
            "alert_name": "CyCraft Cyber Situation Report",
            "alert_type": "CYCRAFT_C",
            "report_id": report_id,
            "customer_name": customer,
            "suspicious_file_count": summary.get("SuspiciousFiles"),
            "suspicious_endpoint_count": summary.get("SuspiciousEndpoints"),
            "suspicious_c2_count": summary.get("SuspiciousC2Cnt"),
        }
        events.append(_apply_stellar_maltrace_aliases({k: v for k, v in event.items() if v is not None}))

    return events


def normalize_incident(
    incident: dict[str, Any],
    *,
    vendor: str,
    source: str,
) -> dict[str, Any]:
    """Flatten XCockpit Incident API row into a Stellar event."""
    uuid = _first_str(incident, "uuid", "UUID") or "unknown"
    tags = incident.get("tags") if isinstance(incident.get("tags"), list) else []
    alert_name = _first_str(incident, "title", "Title") or (
        ", ".join(str(t) for t in tags) if tags else "XCockpit Incident"
    )
    ips = incident.get("ip") if isinstance(incident.get("ip"), list) else []

    event: dict[str, Any] = {
        "vendor": vendor,
        "source": source,
        "event_id": f"incident-{uuid}",
        "event_time": _coerce_timestamp(
            incident.get("last_event_time")
            or incident.get("Last_Event_Time")
            or incident.get("created")
            or incident.get("Created")
        ),
        "severity": "high" if (incident.get("alerted_event_count") or 0) > 0 else "medium",
        "alert_name": alert_name,
        "alert_type": "XCockpit_Incident",
        "incident_uuid": uuid,
        "hostname": _first_str(incident, "computer_name", "Computer_Name"),
        "computer_id": _first_str(incident, "computer_id", "Computer_ID"),
        "src_ip": str(ips[0]) if ips else None,
        "state": incident.get("state"),
        "tags": tags or None,
        "edr_alert_ids": incident.get("edr_alert_ids"),
        "description": _first_str(incident, "graph_summary", "Graph_Summary"),
    }
    return _apply_stellar_maltrace_aliases({k: v for k, v in event.items() if v is not None})


def normalize_cycraft_event(
    payload: dict[str, Any],
    *,
    vendor: str,
    source: str,
) -> dict[str, Any]:
    """Generic normalizer; detects XCockpit EDR report / incident shapes."""
    if payload.get("ReportType") == "CYCRAFT_E" and payload.get("Campaigns"):
        return normalize_edr_alert_report(payload, vendor=vendor, source=source)[0]
    if payload.get("uuid") and payload.get("computer_name"):
        return normalize_incident(payload, vendor=vendor, source=source)

    nested = payload.get("data")
    base = {**nested, **{k: v for k, v in payload.items() if k != "data"}} if isinstance(nested, dict) else dict(payload)

    event_id = _first_str(base, "alert_id", "id", "ReportID", "event_id", "uuid")
    event: dict[str, Any] = {
        "vendor": vendor,
        "source": source,
        "event_id": event_id or _stable_fallback_event_id(base),
        "event_time": _coerce_timestamp(
            base.get("event_time") or base.get("ReportTime") or base.get("created")
        ),
        "severity": _first_str(base, "severity", "Severity", "ReportSeverity") or "unknown",
        "alert_name": _first_str(base, "alert_name", "title", "Title", "name") or "CyCraft alert",
        "hostname": _first_str(base, "hostname", "ComputerName", "computer_name"),
        "src_ip": _first_ip(base),
        "user": _first_str(base, "user", "username", "Account", "account"),
        "process_name": _first_str(base, "process_name", "process", "Subject"),
        "file_hash": _first_str(base, "file_hash", "MD5", "sha256", "hash"),
        "description": _first_str(base, "description", "summary", "graph_summary"),
    }
    return _apply_stellar_maltrace_aliases({k: v for k, v in event.items() if v is not None})
