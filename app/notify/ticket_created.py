"""SOC email notifications (ticket created)."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.config import NotifySettings, get_notify_settings, get_settings
from app.dates import format_detection_time, normalize_epoch_ms
from app.jira.incident_text import format_affected_hosts, format_affected_users
from app.notify.email import parse_email_list, send_email
from app.notify.line_bot import parse_line_recipient_list, send_line_notify
from app.stellar.case_display_name import stellar_case_display_name
from app.stellar.jira_draft import _severity_to_jira_option, stellar_case_detail_lines
from app.stellar.response_action import (
    stellar_notify_disposition_label,
    stellar_subject_detection_phrase,
)

logger = logging.getLogger(__name__)


def _format_subject(template: str, ctx: dict[str, str]) -> str:
    fm: defaultdict[str, str] = defaultdict(str, ctx)
    try:
        subject = template.format_map(fm).strip()
        if subject:
            return subject[:200]
        sev = ctx.get("severity", "")
        name = ctx.get("event_name", "")
        cid = ctx.get("case_id", "")
        return f"{sev}{name}-{cid}"[:200]
    except (KeyError, ValueError, IndexError):
        return f"{ctx.get('severity', '')}{ctx.get('event_name', '')}-{ctx.get('case_id', '')}"[:200]


def _display_severity(severity: str) -> str:
    s = str(severity or "").strip()
    if not s:
        return "-"
    if s.isascii() and s.islower():
        return s.capitalize()
    return s


def _build_stellar_subject(
    *,
    severity: str,
    event_name: str,
    bundle: dict[str, Any] | None,
) -> str:
    phrase = stellar_subject_detection_phrase(bundle)
    name = str(event_name or "").strip()
    sev = str(severity or "").strip()
    disposition = stellar_notify_disposition_label(bundle)
    subject = (
        f"<JJNET XMDR告警>: {phrase}一筆異常資安事件，"
        f"風險等級[{sev}] [{name}][{disposition}]"
    )
    return subject[:200]


def _ai_notify_extra_lines(ai_sections: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Return (prefix, suffix) lines for optional AI content around the case description."""
    ai = ai_sections or {}
    prefix: list[str] = []
    suffix: list[str] = []

    ai_summary = str(ai.get("executive_summary") or "").strip()
    ai_description = str(ai.get("event_description") or "").strip()
    ai_actions = ai.get("recommended_actions")
    action_lines: list[str] = []
    if isinstance(ai_actions, list):
        action_lines = _format_ai_recommended_actions([str(x) for x in ai_actions])

    if ai_summary:
        prefix.extend(["AI SOC 分析師摘要:", ai_summary, ""])

    if ai_description:
        suffix.extend(["事件描述:", ai_description, ""])

    if action_lines:
        suffix.extend(["建議處置作為:", *action_lines, ""])

    if ai_summary or ai_description or action_lines:
        suffix.extend(["（以上 AI 分析僅供參考，請 SOC 人員覆核後執行。）"])

    return prefix, suffix


def _build_stellar_body(
    *,
    case: dict[str, Any],
    bundle: dict[str, Any] | None,
    case_id: str = "",
    timezone_name: str = "Asia/Taipei",
    ai_sections: dict[str, Any] | None = None,
) -> str:
    description_lines = stellar_case_detail_lines(
        case,
        bundle,
        middleware_case_id=case_id or None,
        timezone_name=timezone_name,
    )
    prefix, suffix = _ai_notify_extra_lines(ai_sections)
    parts = [*prefix, "\n".join(description_lines)]
    if suffix:
        parts.extend(["", *suffix])
    return "\n".join(parts)


def _format_detection_time(ms: Any, *, timezone_name: str = "Asia/Taipei") -> str:
    return format_detection_time(ms, timezone_name=timezone_name)


def _incident_detection_time_ms(incident: dict[str, Any]) -> int | None:
    """Prefer primary alert ``detection_timestamp``, then incident ``creation_time``."""
    for key in ("primary_alert_detection_timestamp", "detection_timestamp", "creation_time"):
        ms = normalize_epoch_ms(incident.get(key))
        if ms is not None:
            return ms
    return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _xdr_result_text(incident: dict[str, Any]) -> str:
    pretty = str(incident.get("primary_alert_action_pretty") or "").strip()
    if pretty:
        return pretty
    actions = incident.get("alert_actions")
    if isinstance(actions, list):
        for item in actions:
            s = str(item or "").strip()
            if s:
                return s
    return ""


def _mitre_lines_indented(val: Any) -> list[str]:
    if isinstance(val, list):
        items = [str(x).strip() for x in val if str(x).strip()]
    else:
        s = str(val or "").strip()
        items = [s] if s else []
    return [f"\t   {item}" for item in items]


def _format_ai_recommended_actions(actions: list[str]) -> list[str]:
    lines: list[str] = []
    for i, action in enumerate(actions, start=1):
        text = str(action or "").strip()
        if text:
            lines.append(f"{i}. {text}")
    return lines


def _build_xmdr_notify_body(
    *,
    incident: dict[str, Any],
    case_id: str = "",
    timezone_name: str = "Asia/Taipei",
    response_result_label: str = "XDR結果",
    ai_sections: dict[str, Any] | None = None,
) -> str:
    alert_name = str(incident.get("event_name") or incident.get("description") or "").strip()
    severity = _display_severity(str(incident.get("severity") or ""))
    xdr_result = _xdr_result_text(incident)
    detection_time = _format_detection_time(
        _incident_detection_time_ms(incident),
        timezone_name=timezone_name,
    )
    file_path = str(incident.get("primary_alert_file_path") or "").strip()

    host = str(incident.get("primary_alert_host") or "").strip()
    if not host:
        host = _first_line(format_affected_hosts(incident))

    os_name = str(incident.get("primary_alert_os") or "").strip()

    user = str(incident.get("primary_alert_user") or "").strip()
    if not user:
        user = _first_line(format_affected_users(incident))

    ai = ai_sections or {}
    ai_summary = str(ai.get("executive_summary") or "").strip()
    ai_description = str(ai.get("event_description") or "").strip()
    ai_actions = ai.get("recommended_actions")
    action_lines: list[str] = []
    if isinstance(ai_actions, list):
        action_lines = _format_ai_recommended_actions([str(x) for x in ai_actions])

    lines: list[str] = []
    if ai_summary:
        lines.extend(["AI SOC 分析師摘要:", ai_summary, ""])
    lines.append(f"案件編號: {str(case_id or '').strip()}")
    lines.extend(
        [
            f"告警名稱: {alert_name}",
            f"嚴重程度: {severity}",
            f"{response_result_label}: {xdr_result}",
            f"偵測時間:  {detection_time}",
            f"檔案路徑: {file_path}",
            "",
            "主機資訊",
            f"\t主機名稱/IP: {host}",
            f"\t作業系統: {os_name}",
            f"\t使用者: {user}",
            "\t事件描述:",
        ]
    )
    if ai_description:
        for line in ai_description.splitlines():
            s = line.strip()
            if s:
                lines.append(f"\t{s}")
    else:
        lines.append("")
    lines.append("\tMITRE ATT&CK")
    lines.extend(_mitre_lines_indented(incident.get("mitre_tactics_ids_and_names")))
    lines.extend(["", "建議處置作為:"])
    if action_lines:
        lines.extend(action_lines)
    else:
        lines.append("")
    if ai_summary or ai_description or action_lines:
        lines.extend(["", "（以上 AI 分析僅供參考，請 SOC 人員覆核後執行。）"])
    return "\n".join(lines)


async def notify_ticket_created(
    *,
    jira_key: str,
    case_id: str,
    summary: str,
    customer_code: str,
    source_id: str,
    external_id: str,
    severity: str = "",
    event_name: str = "",
    platform: str = "cortex",
    extra_recipients: list[str] | None = None,
    jira_base_url: str | None = None,
    stellar_case: dict[str, Any] | None = None,
    stellar_bundle: dict[str, Any] | None = None,
    cortex_incident: dict[str, Any] | None = None,
    settings: NotifySettings | None = None,
    decision: dict[str, Any] | None = None,
    ai_sections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send SOC notifications after a ticket is created. Never raises; returns status dict.

    When ``ai_sections`` is already provided (Decision ran AI), reuses it — no second LLM call.
    Optional ``decision`` is passed into the AI prompt so notify text aligns with rules/playbook.
    """
    st = settings or get_notify_settings()
    email_enabled = st.soc_notify_enabled
    line_enabled = st.line_notify_enabled
    if not email_enabled and not line_enabled:
        return {"skipped": True, "reason": "disabled"}

    if platform == "stellar" and isinstance(stellar_case, dict):
        severity = _severity_to_jira_option(str(stellar_case.get("severity") or severity))
        event_name = stellar_case_display_name(stellar_case, stellar_bundle)
    else:
        severity = _display_severity(severity)
        event_name = str(event_name or "").strip()

    ctx = {
        "jira_key": jira_key,
        "case_id": case_id,
        "summary": summary,
        "customer_code": customer_code,
        "severity": severity,
        "event_name": event_name,
        "source_id": source_id,
        "external_id": external_id,
        "platform": platform,
    }
    if platform == "stellar" and isinstance(stellar_case, dict):
        subject = _build_stellar_subject(
            severity=severity,
            event_name=event_name,
            bundle=stellar_bundle,
        )
    else:
        subject = _format_subject(st.soc_notify_subject_template, ctx)

    ai_status: dict[str, Any] | None = None
    if platform == "stellar" and isinstance(stellar_case, dict):
        tz = get_settings().stellar_case_id_timezone
        resolved_ai: dict[str, Any] | None = None
        if isinstance(ai_sections, dict) and (
            ai_sections.get("executive_summary") or ai_sections.get("event_description")
        ):
            ai_status = {"ok": True, "source": "precomputed", **ai_sections}
            resolved_ai = ai_sections
        elif st.soc_notify_ai_configured:
            from app.decision.ai_bridge import generate_ai_aligned_with_decision

            ai_status = await generate_ai_aligned_with_decision(
                case=stellar_case,
                bundle=stellar_bundle,
                middleware_case_id=case_id,
                customer_code=customer_code,
                decision=decision,
                settings=st,
            )
            if ai_status.get("ok"):
                resolved_ai = ai_status
            elif not st.soc_notify_ai_fail_open and email_enabled:
                return {
                    "sent": False,
                    "error": f"ai_failed: {ai_status.get('error') or ai_status.get('reason')}",
                    "ai": ai_status,
                }
        body = _build_stellar_body(
            case=stellar_case,
            bundle=stellar_bundle,
            case_id=case_id,
            timezone_name=tz,
            ai_sections=resolved_ai,
        )
    elif isinstance(cortex_incident, dict):
        tz = get_settings().sync_case_id_timezone
        body = _build_xmdr_notify_body(incident=cortex_incident, case_id=case_id, timezone_name=tz)
    else:
        body = _build_xmdr_notify_body(
            incident={
                "event_name": event_name,
                "severity": severity,
                "creation_time": None,
                "mitre_tactics_ids_and_names": [],
            },
            case_id=case_id,
            timezone_name=get_settings().sync_case_id_timezone,
        )

    result: dict[str, Any] = {}

    if email_enabled:
        to_addrs = parse_email_list(st.soc_notify_to)
        if extra_recipients:
            seen = {a.lower() for a in to_addrs}
            for addr in extra_recipients:
                if addr.lower() not in seen:
                    to_addrs.append(addr)
                    seen.add(addr.lower())
        if not to_addrs:
            result["email"] = {"skipped": True, "reason": "no_recipients"}
        elif not st.is_configured:
            logger.warning(
                "SOC notify enabled but not configured (set RESEND_API_KEY or SMTP_HOST, and SOC_NOTIFY_FROM)"
            )
            result["email"] = {"skipped": True, "reason": "not_configured"}
        else:
            cc_addrs = parse_email_list(st.soc_notify_cc) or None
            bcc_addrs = parse_email_list(st.soc_notify_bcc) or None
            try:
                provider = await send_email(
                    to_addrs=to_addrs,
                    subject=subject,
                    body_text=body,
                    cc_addrs=cc_addrs,
                    bcc_addrs=bcc_addrs,
                    settings=st,
                )
            except Exception as e:
                logger.warning(
                    "SOC notify email failed jira_key=%s case_id=%s recipients=%s: %s",
                    jira_key,
                    case_id,
                    to_addrs,
                    e,
                )
                result["email"] = {"sent": False, "error": str(e), "recipients": to_addrs}
            else:
                logger.info(
                    "SOC notify email sent jira_key=%s provider=%s recipients=%s",
                    jira_key,
                    provider,
                    to_addrs,
                )
                email_result: dict[str, Any] = {
                    "sent": True,
                    "provider": provider,
                    "recipients": to_addrs,
                    "subject": subject,
                }
                if cc_addrs:
                    email_result["cc"] = cc_addrs
                if bcc_addrs:
                    email_result["bcc"] = bcc_addrs
                if platform == "stellar" and isinstance(stellar_case, dict) and ai_status:
                    email_result["ai"] = ai_status
                result["email"] = email_result

    if line_enabled:
        line_to = parse_line_recipient_list(st.line_notify_to)
        if not line_to:
            result["line"] = {"skipped": True, "reason": "no_recipients"}
        elif not st.line_configured:
            logger.warning("LINE notify enabled but LINE_CHANNEL_ACCESS_TOKEN is not set")
            result["line"] = {"skipped": True, "reason": "not_configured"}
        else:
            line_result = await send_line_notify(
                to_ids=line_to,
                subject=subject,
                body_text=body,
                settings=st,
            )
            if line_result.get("sent"):
                logger.info(
                    "SOC notify LINE sent jira_key=%s recipients=%s",
                    jira_key,
                    line_result.get("recipients"),
                )
            result["line"] = line_result

    email_sent = bool(result.get("email", {}).get("sent"))
    line_sent = bool(result.get("line", {}).get("sent"))
    if ai_status is not None:
        result["ai"] = ai_status
    if email_sent or line_sent:
        result["sent"] = True
        if email_sent and isinstance(result.get("email"), dict):
            for key in ("provider", "recipients", "subject"):
                if key in result["email"]:
                    result[key] = result["email"][key]
        return result

    errors: list[str] = []
    for channel in ("email", "line"):
        channel_result = result.get(channel)
        if isinstance(channel_result, dict):
            if channel_result.get("error"):
                errors.append(f"{channel}: {channel_result['error']}")
            elif channel_result.get("errors"):
                errors.append(f"{channel}: {channel_result['errors']}")
            elif channel_result.get("skipped"):
                errors.append(f"{channel}: {channel_result.get('reason', 'skipped')}")
    if errors:
        return {"sent": False, "error": "; ".join(errors), **result}
    return {"sent": False, "reason": "no_channel_sent", **result}
