"""Process Stellar Darktrace alert rows into Cortex-style monthly report data."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from docx.shared import RGBColor

from app.report.report_branding import REPORT_COVER_TITLE, report_platform
from app.report.stellar_darktrace_charts import build_model_alert_stats

RGB_RED = RGBColor(0xD8, 0x31, 0x27)
RGB_AMBER = RGBColor(0xF5, 0xA6, 0x23)
RGB_GREEN = RGBColor(0x4C, 0xAF, 0x50)
RGB_PRIMARY = RGBColor(0x29, 0x33, 0x3A)

TOP_INCIDENTS_COUNT = 10
HIGH_RISK_DEEP_DIVE_COUNT = 5

_STATUS_ACTION = {
    "new": "待處理 / New",
    "in progress": "調查中 / In Progress",
    "escalated": "升級處置 / Escalated",
    "resolved": "已結案 / Resolved",
    "cancelled": "已取消 / Cancelled",
    "closed": "已關閉 / Closed",
}


def _risk_rank(level: str) -> int:
    return {"低": 0, "中": 1, "高": 2}.get(level, 1)


def stellar_case_severity_tier(severity: object) -> str:
    s = str(severity or "").strip().lower()
    if s in ("critical", "high"):
        return "高"
    if s == "medium":
        return "中"
    return "低"


def stellar_alert_risk_tier(row: dict[str, Any]) -> str:
    score_raw = row.get("event_score")
    try:
        score = int(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None
    if score is not None:
        if score >= 80:
            return "高"
        if score >= 50:
            return "中"
        return "低"
    return stellar_case_severity_tier(row.get("case_severity"))


def _parse_mitre_ids(raw: object) -> list[str]:
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []
    parts = re.split(r"[,;\s]+", text)
    out: list[str] = []
    for p in parts:
        tid = p.strip().upper()
        if tid.startswith("T") and len(tid) >= 5:
            out.append(tid)
    return out


def _strip_darktrace_case_label(raw: object) -> str:
    text = str(raw or "").strip()
    if text.lower().startswith("darktrace:"):
        text = text.split(":", 1)[1].strip()
    text = re.sub(r"\s+and\s+\d+\s+others?\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _is_antigena_action_alert(alert_name: str) -> bool:
    name = str(alert_name or "").strip()
    return (
        name.startswith("RESPOND/")
        or name.startswith("Block ")
        or name.startswith("Block all")
        or name.startswith("Enforce ")
    )


def _model_path_segments(name: str) -> list[str]:
    return [part.strip() for part in str(name or "").split("/") if part.strip()]


def infer_darktrace_attack_type(row: dict[str, Any]) -> str:
    """Derive attack/detection category from Darktrace model naming (any model, not a fixed enum)."""
    alert_name = str(row.get("alert_name") or "").strip()
    case_label = _strip_darktrace_case_label(row.get("case_name"))

    source = alert_name
    if _is_antigena_action_alert(alert_name) and case_label:
        source = case_label

    segments = _model_path_segments(source)
    if not segments:
        mitre_ids = _parse_mitre_ids(row.get("darktrace_mitre_id"))
        if mitre_ids:
            return mitre_ids[0]
        return "—"

    if segments[0].lower() == "antigena" and len(segments) >= 3:
        return segments[2]

    if len(segments) >= 2:
        return f"{segments[0]} / {segments[1]}"
    return segments[0]


def build_mitre_summary_from_darktrace_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group by primary MITRE technique id from ``darktrace_mitre_id``."""
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"label": "", "alerts": 0, "case_ids": set(), "max_sev": 0}
    )
    alerts_with_mitre = 0
    case_ids_all: set[str] = set()
    case_ids_with_mitre: set[str] = set()

    for row in rows:
        case_id = str(row.get("case_id") or "")
        if case_id:
            case_ids_all.add(case_id)
        tech_ids = _parse_mitre_ids(row.get("darktrace_mitre_id"))
        if not tech_ids:
            continue
        alerts_with_mitre += 1
        if case_id:
            case_ids_with_mitre.add(case_id)
        primary = tech_ids[0]
        label = primary if len(tech_ids) == 1 else f"{primary} (+{len(tech_ids) - 1})"
        buckets[primary]["label"] = label
        buckets[primary]["alerts"] += 1
        if case_id:
            buckets[primary]["case_ids"].add(case_id)
        rank = {"高": 3, "中": 2, "低": 1}.get(stellar_alert_risk_tier(row), 0)
        buckets[primary]["max_sev"] = max(buckets[primary]["max_sev"], rank)

    def _sev_zh(rank: int) -> str:
        return {3: "高", 2: "中", 1: "低", 0: "—"}[rank]

    summary_rows = [
        (
            buckets[key]["label"],
            _sev_zh(buckets[key]["max_sev"]),
            buckets[key]["alerts"],
            len(buckets[key]["case_ids"]),
        )
        for key in sorted(
            buckets.keys(),
            key=lambda k: (-buckets[k]["alerts"], -len(buckets[k]["case_ids"]), buckets[k]["label"]),
        )
    ]

    unassigned_alerts = len(rows) - alerts_with_mitre
    unassigned_cases = len(case_ids_all) - len(case_ids_with_mitre)
    foot_parts = [
        "統計依 Darktrace alert 的 MITRE technique（darktrace_mitre_id）；",
        f"原始告警 {len(rows)} 則中 {alerts_with_mitre} 則含 MITRE",
    ]
    if unassigned_alerts:
        foot_parts.append(f"（{unassigned_alerts} 則未標註）")
    foot_parts.append(
        f"；聚合 Case {len(case_ids_all)} 起中 {len(case_ids_with_mitre)} 起含 MITRE"
    )
    if unassigned_cases:
        foot_parts.append(f"（{unassigned_cases} 起未標註）")
    foot_parts.append("。各 technique 取第一個 ID 為主要分類。")

    return {
        "rows": summary_rows,
        "footnote": "".join(foot_parts),
        "columns": ["主要 MITRE 技術", "最高嚴重度", "原始告警", "聚合 Case"],
        "empty_message": "（本期 Darktrace 事件無 MITRE technique 標籤）",
        "alerts_total": len(rows),
        "cases_total": len(case_ids_all),
        "alerts_with_mitre": alerts_with_mitre,
        "cases_with_mitre": len(case_ids_with_mitre),
    }


def _unique_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = str(row.get("case_id") or "")
        if not cid:
            continue
        prev = by_id.get(cid)
        if prev is None:
            by_id[cid] = dict(row)
            continue
        if stellar_alert_risk_tier(row) == "高" or (
            stellar_alert_risk_tier(prev) != "高" and stellar_alert_risk_tier(row) == "中"
        ):
            by_id[cid] = dict(row)
    return list(by_id.values())


def _risk_distribution_from_cases(case_rows: list[dict[str, Any]]) -> dict[str, int]:
    high = sum(1 for r in case_rows if stellar_case_severity_tier(r.get("case_severity")) == "高")
    medium = sum(1 for r in case_rows if stellar_case_severity_tier(r.get("case_severity")) == "中")
    low = max(0, len(case_rows) - high - medium)
    return {"高": high, "中": medium, "低": low}


def overall_risk_level(
    rows: list[dict[str, Any]],
    *,
    critical_cases: int = 0,
) -> str:
    case_rows = _unique_cases(rows)
    high_n = sum(1 for r in case_rows if stellar_case_severity_tier(r.get("case_severity")) == "高")
    medium_n = sum(1 for r in case_rows if stellar_case_severity_tier(r.get("case_severity")) == "中")
    crit = max(0, int(critical_cases))
    if crit > 10 or high_n > 10:
        return "高"
    if crit > 0 or high_n > 0 or medium_n > 0:
        return "中"
    return "低"


def _format_write_time(row: dict[str, Any]) -> str:
    wt = row.get("write_time")
    if wt:
        return str(wt).replace(" CST", "").replace(" UTC", "")[-14:] if len(str(wt)) > 14 else str(wt)[:16]
    ms = row.get("write_time_ms")
    if ms:
        try:
            return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).strftime("%m/%d %H:%M")
        except (TypeError, ValueError, OSError):
            pass
    return "N/A"


def _format_trigger_time(row: dict[str, Any]) -> str:
    wt = row.get("write_time")
    if wt:
        return str(wt).strip()
    ms = row.get("write_time_ms")
    if ms:
        try:
            return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        except (TypeError, ValueError, OSError):
            pass
    return "N/A"


def _status_action(status: object) -> str:
    key = str(status or "").strip().lower()
    return _STATUS_ACTION.get(key, str(status or "—"))


def _display_case_name(row: dict[str, Any]) -> str:
    for key in ("case_name", "alert_name"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return "Darktrace 事件"


def _display_hostname(row: dict[str, Any]) -> str:
    val = str(row.get("hostname") or "").strip()
    return val or "—"


def _display_ip(row: dict[str, Any]) -> str:
    val = str(row.get("hostip") or "").strip()
    return val or "—"


def build_high_risk_event_deep_dives(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Pick up to five high-risk alerts for §五 manual deep-dive tables."""
    high_rows = [r for r in rows if stellar_alert_risk_tier(r) == "高"]
    sorted_high = sorted(
        high_rows,
        key=lambda r: (
            int(r.get("event_score") or 0),
            int(r.get("write_time_ms") or 0),
        ),
        reverse=True,
    )
    seen: set[str] = set()
    dives: list[dict[str, str]] = []
    for row in sorted_high:
        dedupe_key = str(row.get("alert_doc_id") or row.get("anomaly_id") or "")
        if not dedupe_key:
            dedupe_key = f"{row.get('case_id')}:{row.get('write_time_ms')}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        dives.append(
            {
                "case_name": _display_case_name(row),
                "trigger_time": _format_trigger_time(row),
                "hostname": _display_hostname(row),
                "ip": _display_ip(row),
                "event_description": "",
                "root_cause_analysis": "",
            }
        )
        if len(dives) >= HIGH_RISK_DEEP_DIVE_COUNT:
            break
    return dives


def process_darktrace_report_data(
    rows: list[dict[str, Any]],
    start_d: date,
    end_d: date,
    *,
    tenant_label: str,
    mttr_val: str = "N/A",
    prev_alerts: int | str = "N/A",
    prev_cases: int | str = "N/A",
    prev_overall_risk: str | None = None,
    mitre_summary: dict | None = None,
) -> dict[str, Any]:
    case_rows = _unique_cases(rows)
    alerts_count = len(rows)
    cases_count = len(case_rows)
    critical_cases = sum(
        1 for r in case_rows if str(r.get("case_severity") or "").strip().lower() == "critical"
    )
    risk_distribution = _risk_distribution_from_cases(case_rows)
    risk_distribution_basis = "Cases"
    overall_risk = overall_risk_level(rows, critical_cases=critical_cases)

    risk_en = {"高": "HIGH", "中": "MEDIUM", "低": "LOW"}.get(overall_risk, overall_risk)
    risk_foot = risk_en
    if prev_overall_risk and prev_overall_risk != overall_risk:
        if _risk_rank(overall_risk) < _risk_rank(prev_overall_risk):
            risk_foot = f"{risk_en} · 較上月下降一級"
        elif _risk_rank(overall_risk) > _risk_rank(prev_overall_risk):
            risk_foot = f"{risk_en} · 較上月上升一級"

    if mttr_val not in ("N/A", "") and str(mttr_val).replace(".", "", 1).isdigit():
        mttr_display = f"{mttr_val} min"
    else:
        mttr_display = mttr_val or "N/A"

    cases_foot = "Stellar Cyber Cases (Darktrace)"
    if critical_cases:
        cases_foot = f"Stellar Cases · 含 {critical_cases} 起 Critical"

    sorted_rows = sorted(
        rows,
        key=lambda r: (
            {"高": 3, "中": 2, "低": 1}.get(stellar_alert_risk_tier(r), 0),
            int(r.get("event_score") or 0),
            int(r.get("write_time_ms") or 0),
        ),
        reverse=True,
    )

    top_incidents: list[tuple[str, str, str, str, str, str, str]] = []
    for i, row in enumerate(sorted_rows[:TOP_INCIDENTS_COUNT], 1):
        dt = _format_write_time(row)
        attack_type = infer_darktrace_attack_type(row)
        desc = str(row.get("alert_name") or row.get("case_name") or "Darktrace 事件")[:120]
        if row.get("hostip"):
            desc = f"{desc} ({row.get('hostip')})"
        action = _status_action(row.get("case_status"))
        risk = stellar_alert_risk_tier(row)
        top_incidents.append((str(i), dt, attack_type, desc, action, "", risk))

    while len(top_incidents) < TOP_INCIDENTS_COUNT:
        n = len(top_incidents) + 1
        top_incidents.append((str(n), "-", "-", "無資料", "-", "", "低"))

    executive_summary_runs = [
        ("本月 Stellar Cyber Darktrace 共 ", False, None),
        (f"{alerts_count:,}", True, RGB_RED),
        (" 筆原始告警（Alerts）、", False, None),
        (f"{cases_count:,}", True, RGB_PRIMARY),
        (f" 筆聚合 Case；{risk_distribution_basis} ", False, None),
        ("高風險 ", False, None),
        (f"{risk_distribution['高']}", True, RGB_RED),
        (" 起、中風險 ", False, None),
        (f"{risk_distribution['中']}", True, RGB_AMBER),
        (" 起、低風險 ", False, None),
        (f"{risk_distribution['低']}", True, RGB_GREEN),
        (" 起。整體風險評等為 ", False, None),
        (f"「{overall_risk}」", True, RGB_AMBER),
        ("，詳細偵測指標與處置情形如下：", False, None),
    ]

    return {
        "client_name": tenant_label,
        "period": f"{start_d} – {end_d}",
        "period_short": f"{start_d.strftime('%Y-%m')}",
        "service_owner": "MDR SOC Team",
        "version": f"v1.0 / {datetime.now().strftime('%Y-%m-%d')}",
        "platform": report_platform("Darktrace"),
        "overall_risk": overall_risk,
        "issues_count": alerts_count,
        "cases_count": cases_count,
        "confidential_line": "Confidential — Darktrace MDR Monthly Report",
        "cover": {
            "title": REPORT_COVER_TITLE,
            "subtitle": "月度資安營運報告",
            "subtitle_en": "Monthly Security Operations Report",
            "tagline": "Network  ·  Antigena  ·  SaaS & Cloud",
        },
        "executive_summary_runs": executive_summary_runs,
        "kpi": [
            ("原始告警\nOriginal Alerts", alerts_count, prev_alerts, True, "Darktrace Alerts"),
            ("聚合事件\nAggregated Cases", cases_count, prev_cases, True, cases_foot),
            ("MTTR (分鐘)\nMean MTTR", mttr_display, "N/A", True, "Jira AIxSOC 已結案工單"),
            ("整體風險\nOverall Risk", overall_risk, prev_overall_risk or "N/A", False, risk_foot),
        ],
        "model_alerts_stats": build_model_alert_stats(rows),
        "model_alerts_heading": "二、事件等級類別及事件分數統計",
        "mitre_summary": mitre_summary or build_mitre_summary_from_darktrace_rows(rows),
        "mitre_heading": "三、MITRE 技術摘要 MITRE Technique Summary",
        "top_count": TOP_INCIDENTS_COUNT,
        "top_section_title": f"四、本月重點 Darktrace 事件 Top {TOP_INCIDENTS_COUNT}",
        "top_columns": ["#", "發生日期", "攻擊類型", "事件描述 Description", "Case 狀態", "處理進度", "風險"],
        "top_col_widths_cm": [0.8, 2.0, 2.6, 4.8, 2.4, 2.0, 1.4],
        "incidents": top_incidents,
        "event_deep_dive_heading": "五、事件報告說明",
        "event_deep_dives": build_high_risk_event_deep_dives(rows),
        "recommendations_heading": "六、整體建議 Recommendations",
        "recommendations": [
            (
                "檢視 Darktrace 模型與 Antigena 回應規則",
                "針對本期高風險事件複核模型觸發條件，必要時調整 Antigena 封鎖／隔離策略以降低誤報。",
                "高",
            ),
            (
                "強化內網異常連線監控",
                "建議對本期出現之可疑 outbound / lateral movement 建立觀察清單並持續追蹤。",
                "中",
            ),
            (
                "同步 Stellar Case 與 Jira AIxSOC 工單",
                "確保 Darktrace 事件在 Stellar 與 Jira 的狀態、指派與備註一致，以利 MTTR 統計。",
                "低",
            ),
        ],
    }
