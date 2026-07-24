"""Build Jira issue fields from a Stellar Cyber case bundle (AIxSOC line)."""

from __future__ import annotations

import re
from typing import Any

from app.dates import format_detection_time
from app.jira.adf import plain_text_to_adf
from app.stellar.alert_fields import stellar_primary_file_path
from app.stellar.case_display_name import stellar_case_display_name
from app.stellar.response_action import stellar_response_action_text
from app.stellar.resolution_tag import (
    jira_field_payload_for_resolution_tag,
    jira_resolution_tag_from_case,
    load_resolution_tag_map,
)


def _severity_to_jira_option(sev: str) -> str:
    """Map Stellar severity to Jira 嚴重程度 option (customfield_10057: Low/Medium/High/Critical)."""
    s = str(sev or "Medium").strip()
    if not s:
        return "Medium"
    low = s.lower()
    for label in ("Critical", "High", "Medium", "Low"):
        if low == label.lower():
            return label
    return s.capitalize() if s.isascii() else s


_STELLAR_STATUS_LABELS = ("New", "Escalated", "In Progress", "Resolved", "Cancelled")


def _stellar_status_to_jira_option(status: str) -> str | None:
    """Map Stellar ``status`` → Jira 事件狀態 (same option labels on AIxSOC)."""
    s = str(status or "").strip()
    if not s:
        return None
    low = s.lower()
    for label in _STELLAR_STATUS_LABELS:
        if low == label.lower():
            return label
    return s if s in _STELLAR_STATUS_LABELS else None


def _alert_names(alerts_payload: Any, *, limit: int = 5) -> list[str]:
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    names: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        name = src.get("name") or src.get("display_name") or src.get("title")
        if name and str(name).strip() and str(name).strip() not in names:
            names.append(str(name).strip())
        if len(names) >= limit:
            break
    return names


def _host_line(host: Any) -> str | None:
    if not isinstance(host, dict):
        return None
    hostname = str(host.get("hostname") or "").strip()
    ip = str(host.get("ip") or "").strip()
    if hostname and ip:
        return f"host: {hostname} ({ip})"
    if hostname:
        return f"host: {hostname}"
    if ip:
        return f"host: {ip}"
    return None


def _process_line(path: str) -> str | None:
    text = str(path or "").strip()
    if not text:
        return None
    norm = text.replace("\\", "/")
    basename = norm.rsplit("/", 1)[-1]
    if basename and basename != text and basename != norm:
        return f"process: {basename} ({text})"
    if basename:
        return f"process: {basename}"
    return f"process: {text}"


def _file_line(bundle: dict[str, Any], primary_path: str) -> str | None:
    obs_payload = bundle.get("observables")
    if not isinstance(obs_payload, dict):
        return None
    obs = obs_payload.get("observables")
    if not isinstance(obs, dict):
        return None
    files = obs.get("file")
    if not isinstance(files, list) or not files:
        return None
    last = files[-1]
    if not isinstance(last, dict):
        return None
    file_name = str(last.get("file_name") or "").strip()
    if not file_name:
        return None
    primary_norm = str(primary_path or "").strip().replace("\\", "/").lower()
    file_norm = file_name.replace("\\", "/").lower()
    primary_base = primary_norm.rsplit("/", 1)[-1] if primary_norm else ""
    file_base = file_norm.rsplit("/", 1)[-1] if file_norm else ""
    if primary_norm and (file_norm == primary_norm or (file_base and file_base == primary_base)):
        return None
    return f"file: {file_name}"


def _detail_lines(bundle: dict[str, Any] | None, *, limit: int = 8) -> list[str]:
    """Detail block: hosts, users, process (scored path), optional file."""
    bundle = bundle or {}
    lines: list[str] = []
    obs_payload = bundle.get("observables")
    obs = obs_payload.get("observables") if isinstance(obs_payload, dict) else None
    if isinstance(obs, dict):
        for host in obs.get("host") or []:
            if len(lines) >= limit:
                break
            host_line = _host_line(host)
            if host_line:
                lines.append(host_line)
        seen_users: set[str] = set()
        for user in obs.get("user") or []:
            if len(lines) >= limit:
                break
            if not isinstance(user, dict):
                continue
            username = str(user.get("username") or "").strip()
            if not username:
                continue
            low = username.lower()
            if low in seen_users:
                continue
            seen_users.add(low)
            lines.append(f"user: {username}")

    primary_path = stellar_primary_file_path(bundle)
    process_line = _process_line(primary_path)
    if process_line and len(lines) < limit:
        lines.append(process_line)
    file_line = _file_line(bundle, primary_path)
    if file_line and len(lines) < limit:
        lines.append(file_line)
    return lines[:limit]


def stellar_case_detail_lines(
    case: dict[str, Any],
    bundle: dict[str, Any] | None = None,
    *,
    middleware_case_id: str | None = None,
    customer_code: str = "",
    tenant_name: str = "",
    tenant_id: str = "",
    timezone_name: str = "Asia/Taipei",
) -> list[str]:
    """Plain-text lines for Jira issue description (display only)."""
    bundle = bundle or {}
    severity = str(case.get("severity") or "Medium")
    severity_option = _severity_to_jira_option(severity)
    ticket_id = case.get("ticket_id")
    case_name = stellar_case_display_name(case, bundle)
    alert_names = _alert_names(bundle.get("alerts"))
    detection_time = format_detection_time(case.get("created_at"), timezone_name=timezone_name)
    response_result = stellar_response_action_text(bundle)

    lines: list[str] = []
    if tenant_name:
        lines.append(f"Tenant: {tenant_name}")
    if tenant_id:
        lines.append(f"Tenant ID: {tenant_id}")
    if ticket_id is not None and str(ticket_id).strip() != "":
        lines.append(f"AIxSOC Ticket ID: {ticket_id}")
    if middleware_case_id:
        lines.append(f"案件編號: {middleware_case_id}")
    lines.append(f"告警名稱: {case_name[:500]}")
    lines.append(f"嚴重程度: {severity_option}")
    if detection_time:
        lines.append(f"偵測時間: {detection_time}")
    lines.append(f"自動回應結果: {response_result}")
    if alert_names:
        lines.append("Alerts (sample):")
        lines.extend(f"  - {n}" for n in alert_names)
    detail_lines = _detail_lines(bundle)
    if detail_lines:
        lines.append("Detail:")
        lines.extend(f"  - {x}" for x in detail_lines)
    summary_data = bundle.get("summary")
    if isinstance(summary_data, dict):
        inner = summary_data.get("data")
        if isinstance(inner, dict):
            tactics = inner.get("tactics")
            if isinstance(tactics, list) and tactics:
                lines.append("MITRE Tactics: " + ", ".join(str(t) for t in tactics[:12]))
    return lines


def build_jira_issue_fields(
    *,
    project_key: str,
    issue_type_id: str,
    severity_field_id: str = "customfield_10057",
    status_field_id: str = "customfield_10061",
    alert_name_field_id: str | None = "customfield_10122",
    resolution_tag_field_id: str | None = "customfield_10201",
    case_id_jira_field: str = "customfield_10060",
    summary_template: str = "[{severity}][{event_name}][{customer_code}]",
    customer_code: str,
    tenant_source_id: str = "",
    tenant_name: str = "",
    tenant_id: str = "",
    tenant_labels: list[str] | None = None,
    middleware_case_id: str | None = None,
    case: dict[str, Any],
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create-issue fields for Stellar → Jira (same 案件編號 / summary 慣例 as Cortex line)."""
    bundle = bundle or {}
    severity = str(case.get("severity") or "Medium")
    severity_option = _severity_to_jira_option(severity)
    stellar_case_id = str(case.get("_id") or bundle.get("case_id") or "")
    status = case.get("status")
    status_option = _stellar_status_to_jira_option(str(status or ""))
    case_name = stellar_case_display_name(case, bundle)
    cc = customer_code.strip().upper()
    event_name = case_name[:80]

    fm = {
        "severity": severity_option,
        "event_name": event_name,
        "customer_code": cc,
        "客戶代號": cc,
    }
    summary = summary_template.format_map(fm)[:254]

    from app.config import get_stellar_settings

    tz = get_stellar_settings().stellar_case_id_timezone
    lines = stellar_case_detail_lines(
        case,
        bundle,
        middleware_case_id=middleware_case_id,
        customer_code=cc,
        tenant_name=tenant_name,
        tenant_id=tenant_id,
        timezone_name=tz,
    )

    description_adf = plain_text_to_adf("\n".join(lines))
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "issuetype": {"id": issue_type_id},
        "summary": summary,
        "description": description_adf,
    }
    if severity_field_id:
        fields[severity_field_id] = {"value": severity_option}
    if status_field_id and status_option:
        fields[status_field_id] = {"value": status_option}
    if alert_name_field_id and case_name:
        fields[alert_name_field_id] = plain_text_to_adf(case_name[:32000])
    if resolution_tag_field_id:
        rmap = load_resolution_tag_map()
        res_label = jira_resolution_tag_from_case(case, rmap)
        if res_label:
            fields[resolution_tag_field_id] = jira_field_payload_for_resolution_tag(
                res_label, rmap
            )
    if middleware_case_id and case_id_jira_field:
        fields[case_id_jira_field] = middleware_case_id
    labels = ["stellar-cyber", "aixsoc"]
    tenant_slug = re.sub(
        r"[^a-z0-9_-]+", "-", str(tenant_source_id or "").strip().lower()
    ).strip("-")
    if tenant_slug:
        labels.append(f"tenant-{tenant_slug}")
    for label in tenant_labels or []:
        clean = re.sub(r"[^A-Za-z0-9_-]+", "-", str(label or "").strip()).strip("-")
        if clean and clean not in labels:
            labels.append(clean)
    if stellar_case_id:
        labels.append(f"stellar-case-{stellar_case_id[:12]}")
    fields["labels"] = labels
    return fields
