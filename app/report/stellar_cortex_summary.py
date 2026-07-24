"""Process Stellar Cortex XDR alert rows into monthly report data."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from docx.shared import RGBColor

from app.stellar.case_display_name import clean_stellar_case_name
from app.report.report_branding import REPORT_COVER_TITLE, report_platform
from app.report.stellar_cortex_charts import build_cortex_alert_stats
from app.report.stellar_darktrace_summary import (
    HIGH_RISK_DEEP_DIVE_COUNT,
    TOP_INCIDENTS_COUNT,
    _STATUS_ACTION,
    _risk_rank,
    overall_risk_level,
    stellar_case_severity_tier,
)

RGB_RED = RGBColor(0xD8, 0x31, 0x27)
RGB_AMBER = RGBColor(0xF5, 0xA6, 0x23)
RGB_GREEN = RGBColor(0x4C, 0xAF, 0x50)
RGB_PRIMARY = RGBColor(0x29, 0x33, 0x3A)

_TACTIC_ID_RE = re.compile(r"(TA\d{4})", re.I)


def _primary_tactic_key(tactics: list[str]) -> str:
    if not tactics:
        return ""
    first = str(tactics[0]).strip()
    m = _TACTIC_ID_RE.search(first)
    if m:
        return m.group(1).upper()
    return first


def _primary_tactic_label(tactics: list[str]) -> str:
    if not tactics:
        return ""
    return str(tactics[0]).strip()


def build_mitre_summary_from_cortex_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group by primary MITRE tactic from case ``mitre_tactics``."""
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
        tactics = row.get("mitre_tactics")
        if not isinstance(tactics, list) or not tactics:
            continue
        key = _primary_tactic_key(tactics)
        if not key:
            continue
        alerts_with_mitre += 1
        if case_id:
            case_ids_with_mitre.add(case_id)
        buckets[key]["label"] = _primary_tactic_label(tactics)
        buckets[key]["alerts"] += 1
        if case_id:
            buckets[key]["case_ids"].add(case_id)
        rank = {"高": 3, "中": 2, "低": 1}.get(stellar_case_severity_tier(row.get("case_severity")), 0)
        buckets[key]["max_sev"] = max(buckets[key]["max_sev"], rank)

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
        "統計依 Stellar case summary 的 MITRE 戰術（tactics）；",
        f"原始告警 {len(rows)} 則中 {alerts_with_mitre} 則含 MITRE",
    ]
    if unassigned_alerts:
        foot_parts.append(f"（{unassigned_alerts} 則未標註）")
    foot_parts.append(
        f"；聚合 Case {len(case_ids_all)} 起中 {len(case_ids_with_mitre)} 起含 MITRE"
    )
    if unassigned_cases:
        foot_parts.append(f"（{unassigned_cases} 起未標註）")
    foot_parts.append("。各戰術取第一筆為主要分類。")

    return {
        "rows": summary_rows,
        "footnote": "".join(foot_parts),
        "columns": ["主要 MITRE 戰術", "最高嚴重度", "原始告警", "聚合 Case"],
        "empty_message": "（本期 Cortex XDR 事件無 MITRE 戰術標籤）",
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
        if stellar_case_severity_tier(row.get("case_severity")) == "高" or (
            stellar_case_severity_tier(prev.get("case_severity")) != "高"
            and stellar_case_severity_tier(row.get("case_severity")) == "中"
        ):
            by_id[cid] = dict(row)
    return list(by_id.values())


def _risk_distribution_from_cases(case_rows: list[dict[str, Any]]) -> dict[str, int]:
    high = sum(1 for r in case_rows if stellar_case_severity_tier(r.get("case_severity")) == "高")
    medium = sum(1 for r in case_rows if stellar_case_severity_tier(r.get("case_severity")) == "中")
    low = max(0, len(case_rows) - high - medium)
    return {"高": high, "中": medium, "低": low}


def _format_case_time(row: dict[str, Any]) -> str:
    wt = row.get("case_created_at") or row.get("write_time")
    if wt:
        text = str(wt).strip()
        return text.replace(" CST", "").replace(" UTC", "")[-14:] if len(text) > 14 else text[:16]
    ms = row.get("case_created_ms") or row.get("write_time_ms")
    if ms:
        try:
            return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).strftime("%m/%d %H:%M")
        except (TypeError, ValueError, OSError):
            pass
    return "N/A"


def _format_case_trigger_time(row: dict[str, Any]) -> str:
    wt = row.get("case_created_at") or row.get("write_time")
    if wt:
        return str(wt).strip()
    ms = row.get("case_created_ms") or row.get("write_time_ms")
    if ms:
        try:
            return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        except (TypeError, ValueError, OSError):
            pass
    return "N/A"


def _case_sort_key(row: dict[str, Any]) -> tuple[int, int]:
    rank = {"高": 3, "中": 2, "低": 1}.get(stellar_case_severity_tier(row.get("case_severity")), 0)
    ts = int(row.get("case_created_ms") or row.get("write_time_ms") or 0)
    return rank, ts


def _status_action(status: object) -> str:
    key = str(status or "").strip().lower()
    return _STATUS_ACTION.get(key, str(status or "—"))


def infer_cortex_detection_category(row: dict[str, Any]) -> str:
    cat = str(row.get("alert_category") or "").strip()
    if cat:
        return cat
    text = f"{row.get('alert_name') or ''} {row.get('case_name') or ''}".lower()
    if any(k in text for k in ("identity", "login", "oauth", "impossible")):
        return "Identity & Cloud"
    if any(k in text for k in ("network", "c2", "firewall", "port scan")):
        return "Network"
    return "Endpoint"


def build_top_cortex_cases(rows: list[dict[str, Any]]) -> list[tuple[str, str, str, str, str, str, str]]:
    """Top incidents table: one row per Stellar Case (not per alert)."""
    sorted_cases = sorted(_unique_cases(rows), key=_case_sort_key, reverse=True)
    top_incidents: list[tuple[str, str, str, str, str, str, str]] = []
    for i, row in enumerate(sorted_cases[:TOP_INCIDENTS_COUNT], 1):
        dt = _format_case_time(row)
        category = infer_cortex_detection_category(row)
        desc = clean_stellar_case_name(str(row.get("case_name") or row.get("alert_name") or ""))[:120]
        if not desc:
            desc = "Cortex XDR 事件"
        if row.get("hostip"):
            desc = f"{desc} ({row.get('hostip')})"
        action = _status_action(row.get("case_status"))
        disposition = str(row.get("response_action") or "").strip() or "—"
        risk = stellar_case_severity_tier(row.get("case_severity"))
        top_incidents.append((str(i), dt, category, desc, action, disposition, risk))

    while len(top_incidents) < TOP_INCIDENTS_COUNT:
        n = len(top_incidents) + 1
        top_incidents.append((str(n), "-", "-", "無資料", "-", "—", "低"))
    return top_incidents


def build_high_risk_event_deep_dives(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Pick up to five high-risk Cases for §五 manual deep-dive tables."""
    case_rows = _unique_cases(rows)
    high_cases = [r for r in case_rows if stellar_case_severity_tier(r.get("case_severity")) == "高"]
    sorted_high = sorted(high_cases, key=_case_sort_key, reverse=True)
    dives: list[dict[str, str]] = []
    for row in sorted_high[:HIGH_RISK_DEEP_DIVE_COUNT]:
        name = clean_stellar_case_name(str(row.get("case_name") or row.get("alert_name") or ""))
        dives.append(
            {
                "case_name": name or "Cortex XDR 事件",
                "trigger_time": _format_case_trigger_time(row),
                "hostname": str(row.get("hostname") or "—"),
                "ip": str(row.get("hostip") or "—"),
                "event_description": "",
                "root_cause_analysis": "",
            }
        )
    return dives


def process_cortex_report_data(
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

    cases_foot = "Stellar Cyber Cases (Cortex XDR)"
    if critical_cases:
        cases_foot = f"Stellar Cases · 含 {critical_cases} 起 Critical"

    top_incidents = build_top_cortex_cases(rows)

    executive_summary_runs = [
        ("本月 Stellar Cyber Cortex XDR 共 ", False, None),
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
        "platform": report_platform("Cortex XDR"),
        "overall_risk": overall_risk,
        "issues_count": alerts_count,
        "cases_count": cases_count,
        "confidential_line": "Confidential — Cortex XDR MDR Monthly Report",
        "cover": {
            "title": REPORT_COVER_TITLE,
            "subtitle": "月度資安營運報告",
            "subtitle_en": "Monthly Security Operations Report",
            "tagline": "Endpoint  ·  Network  ·  Identity & Cloud",
        },
        "executive_summary_runs": executive_summary_runs,
        "kpi": [
            ("原始告警\nOriginal Alerts", alerts_count, prev_alerts, True, "Cortex XDR Alerts"),
            ("聚合事件\nAggregated Cases", cases_count, prev_cases, True, cases_foot),
            ("MTTR (分鐘)\nMean MTTR", mttr_display, "N/A", True, "Jira AIxSOC 已結案工單"),
            ("整體風險\nOverall Risk", overall_risk, prev_overall_risk or "N/A", False, risk_foot),
        ],
        "model_alerts_stats": build_cortex_alert_stats(rows),
        "model_alerts_heading": "二、告警嚴重度與偵測類別統計",
        "mitre_summary": mitre_summary or build_mitre_summary_from_cortex_rows(rows),
        "mitre_heading": "三、MITRE 戰術摘要 MITRE Tactic Summary",
        "top_count": TOP_INCIDENTS_COUNT,
        "top_section_title": f"四、本月重點 Cortex XDR Case Top {TOP_INCIDENTS_COUNT}",
        "top_columns": ["#", "發生日期", "偵測類別", "事件描述 Description", "Case 狀態", "處置結果", "風險"],
        "top_col_widths_cm": [0.8, 2.0, 2.4, 4.6, 2.2, 2.2, 1.4],
        "incidents": top_incidents,
        "event_deep_dive_heading": "五、事件報告說明",
        "event_deep_dives": build_high_risk_event_deep_dives(rows),
        "recommendations_heading": "六、整體建議 Recommendations",
        "recommendations": [
            (
                "更新 Cortex XDR Agent 至最新版本",
                "建議檢視本期受影響端點的 Agent 版本與覆蓋率，統一升級以降低已知漏洞與偵測缺口。",
                "高",
            ),
            (
                "檢視例外清單與 BIOC/IOC 調校",
                "針對本期高頻或誤報類別調整例外與規則，降低雜訊並保留對真實威脅的敏感度。",
                "中",
            ),
            (
                "同步 Stellar Case 與 Jira AIxSOC 工單",
                "確保 Cortex XDR 事件在 Stellar 與 Jira 的狀態、指派與備註一致，以利 MTTR 統計。",
                "低",
            ),
        ],
    }
