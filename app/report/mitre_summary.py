"""Aggregate Issues/Cases by primary MITRE tactic for monthly report tables."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_MITRE_ID_RE = re.compile(r"^(TA\d{4}|T\d{4}(?:\.\d{3})?)$", re.IGNORECASE)


def _split_mitre_entry(item: str) -> tuple[str, str]:
    """Parse one ``mitre_*_ids_and_names`` entry → (id, display_name)."""
    s = str(item).strip()
    if not s:
        return "", ""
    if " - " in s:
        left, right = s.split(" - ", 1)
        tid = left.strip()
        name = right.strip()
        return tid, name or tid
    if _MITRE_ID_RE.match(s):
        return s.upper() if s[0].lower() == "t" and not s.upper().startswith("TA") else s, s
    return "", s


def _parse_mitre_field_entries(raw: object) -> list[tuple[str, str]]:
    if not raw:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[tuple[str, str]] = []
    for item in items:
        mid, name = _split_mitre_entry(str(item))
        if mid or name:
            out.append((mid, name))
    return out


def parse_mitre_tactic_entries(obj: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (tactic_id, name) pairs from ``mitre_tactics_ids_and_names``."""
    return _parse_mitre_field_entries(obj.get("mitre_tactics_ids_and_names"))


def parse_mitre_technique_entries(obj: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (technique_id, name) pairs from ``mitre_techniques_ids_and_names``."""
    return _parse_mitre_field_entries(obj.get("mitre_techniques_ids_and_names"))


def format_mitre_tactic_label(tactic_id: str, name: str) -> str:
    """e.g. ``Discovery [TA0007]`` — 戰術名稱 + 方括號代號。"""
    if tactic_id:
        label = name or tactic_id
        return f"{label} [{tactic_id}]"
    return name


def parse_mitre_tactics(obj: dict[str, Any]) -> list[str]:
    """Return human-readable tactic names (without IDs)."""
    return [name for _, name in parse_mitre_tactic_entries(obj)]


def primary_mitre_tactic(obj: dict[str, Any]) -> str | None:
    """Primary tactic display label with ID, e.g. ``Discovery [TA0007]``."""
    entries = parse_mitre_tactic_entries(obj)
    if not entries:
        return None
    tid, name = entries[0]
    return format_mitre_tactic_label(tid, name)


def format_primary_technique_suffix(tech_id: str, name: str) -> str:
    """Append primary technique, e.g. `` · T1059.001``."""
    if tech_id:
        return f" · {tech_id}"
    if name:
        return f" · {name}"
    return ""


def primary_mitre_technique(obj: dict[str, Any]) -> str | None:
    """Primary technique id or name only (first entry)."""
    entries = parse_mitre_technique_entries(obj)
    if not entries:
        return None
    tid, name = entries[0]
    return tid or name


def primary_mitre_display(obj: dict[str, Any]) -> str | None:
    """Tactic + optional primary technique, e.g. ``Discovery [TA0007] · T1059.001``."""
    tactic_label = primary_mitre_tactic(obj)
    if not tactic_label:
        return None
    entries = parse_mitre_technique_entries(obj)
    if not entries:
        return tactic_label
    tid, name = entries[0]
    return tactic_label + format_primary_technique_suffix(tid, name)


def primary_mitre_tactic_key(obj: dict[str, Any]) -> str | None:
    """Stable bucket key: tactic id if present, else name."""
    entries = parse_mitre_tactic_entries(obj)
    if not entries:
        return None
    tid, name = entries[0]
    return tid or name


def _severity_rank(sev: object) -> int:
    s = str(sev or "").strip().lower()
    if s in ("critical", "high"):
        return 3
    if s == "medium":
        return 2
    if s == "low":
        return 1
    return 0


def _severity_label_zh(rank: int) -> str:
    return {3: "高", 2: "中", 1: "低", 0: "—"}[rank]


def build_mitre_summary(
    issues: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Group by **primary** MITRE tactic (first entry in ``mitre_tactics_ids_and_names``).

    - 原始告警: Issues linked via ``case_ids`` to a Case that has MITRE
    - 聚合事件: distinct Cases with MITRE per tactic
    """
    case_by_id: dict[str, dict[str, Any]] = {}
    for case in cases:
        cid = str(case.get("case_id") or "").strip()
        if cid:
            case_by_id[cid] = case

    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"label": "", "issues": 0, "case_ids": set(), "max_sev": 0}
    )

    cases_with_mitre = 0
    for case in cases:
        key = primary_mitre_tactic_key(case)
        if not key:
            continue
        cases_with_mitre += 1
        buckets[key]["label"] = primary_mitre_display(case) or key
        buckets[key]["case_ids"].add(str(case.get("case_id") or ""))
        buckets[key]["max_sev"] = max(
            buckets[key]["max_sev"],
            _severity_rank(case.get("severity")),
        )

    issues_with_mitre = 0
    for issue in issues:
        cids = issue.get("case_ids")
        if not isinstance(cids, list):
            continue
        for cid in cids:
            case = case_by_id.get(str(cid))
            if case is None:
                continue
            key = primary_mitre_tactic_key(case)
            if not key:
                continue
            buckets[key]["label"] = primary_mitre_display(case) or key
            buckets[key]["issues"] += 1
            buckets[key]["max_sev"] = max(
                buckets[key]["max_sev"],
                _severity_rank(issue.get("severity")),
                _severity_rank(case.get("severity")),
            )
            issues_with_mitre += 1
            break

    rows: list[tuple[str, str, int, int]] = []
    for key in sorted(
        buckets.keys(),
        key=lambda k: (-buckets[k]["issues"], -len(buckets[k]["case_ids"]), buckets[k]["label"]),
    ):
        b = buckets[key]
        rows.append(
            (
                b["label"],
                _severity_label_zh(b["max_sev"]),
                b["issues"],
                len(b["case_ids"]),
            )
        )

    unassigned_issues = len(issues) - issues_with_mitre
    unassigned_cases = len(cases) - cases_with_mitre
    footnote_parts = [
        "統計僅含具 MITRE 戰術標籤之事件；"
        f"原始告警 {len(issues)} 則中 {issues_with_mitre} 則可對應戰術",
    ]
    if unassigned_issues:
        footnote_parts.append(f"（{unassigned_issues} 則未標註）")
    footnote_parts.append(
        f"；聚合事件 {len(cases)} 起中 {cases_with_mitre} 起含 MITRE"
    )
    if unassigned_cases:
        footnote_parts.append(f"（{unassigned_cases} 起未標註）")
    footnote_parts.append(
        "。主要戰術／技術各取第一筆（例：Discovery [TA0007] · T1059.001）。"
    )

    return {
        "rows": rows,
        "footnote": "".join(footnote_parts),
        "issues_total": len(issues),
        "cases_total": len(cases),
        "issues_with_mitre": issues_with_mitre,
        "cases_with_mitre": cases_with_mitre,
    }


def build_mitre_summary_from_incidents(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    """Offline fallback: MITRE from Incidents only (Issues/Cases columns use incident counts)."""
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"label": "", "incidents": 0, "max_sev": 0}
    )
    with_mitre = 0
    for inc in incidents:
        key = primary_mitre_tactic_key(inc)
        if not key:
            continue
        with_mitre += 1
        buckets[key]["label"] = primary_mitre_display(inc) or key
        buckets[key]["incidents"] += 1
        buckets[key]["max_sev"] = max(
            buckets[key]["max_sev"],
            _severity_rank(inc.get("severity")),
        )

    rows = [
        (
            buckets[key]["label"],
            _severity_label_zh(buckets[key]["max_sev"]),
            buckets[key]["incidents"],
            buckets[key]["incidents"],
        )
        for key in sorted(
            buckets.keys(),
            key=lambda k: (-buckets[k]["incidents"], buckets[k]["label"]),
        )
    ]
    footnote = (
        f"離線模式：僅依快取 Incidents 彙整（{len(incidents)} 起中 {with_mitre} 起含 MITRE）。"
        "原始告警／聚合事件欄位以 Incident 筆數代替；連線 API 後改為 Issue／Case 統計。"
    )
    return {
        "rows": rows,
        "footnote": footnote,
        "issues_total": len(incidents),
        "cases_total": len(incidents),
        "issues_with_mitre": with_mitre,
        "cases_with_mitre": with_mitre,
        "offline": True,
    }
