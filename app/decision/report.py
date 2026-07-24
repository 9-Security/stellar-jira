"""Pilot ROI / decision audit report for MSSP sales & internal Go/No-Go."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.decision.store import DecisionStore


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def compute_decision_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate decision audit metrics used for pilot ROI."""
    total = len(events)
    actions = Counter(str(e.get("action") or "") for e in events)
    escalations = Counter(str(e.get("escalation") or "") for e in events)
    with_outcome_at = [e for e in events if e.get("outcome_at")]
    labeled = [
        e
        for e in events
        if e.get("outcome_true_positive") is True or e.get("outcome_true_positive") is False
    ]
    tp = sum(1 for e in labeled if e.get("outcome_true_positive") is True)
    fp = sum(1 for e in labeled if e.get("outcome_true_positive") is False)
    unknown_stamp = sum(
        1 for e in with_outcome_at if e.get("outcome_true_positive") is None
    )
    notify_customer = sum(1 for e in events if e.get("notify_customer"))
    isolate_advisory = sum(1 for e in events if e.get("isolate_host"))
    l2_or_ir = sum(1 for e in events if str(e.get("escalation") or "") in ("L2", "IR"))
    deferred = actions.get("defer", 0) + actions.get("suppress", 0)

    # Labeled coverage is what closes the Dataset loop for Go/No-Go
    labeled_rate = (len(labeled) / total) if total else 0.0
    stamp_rate = (len(with_outcome_at) / total) if total else 0.0
    labeled_denom = tp + fp
    fp_rate = (fp / labeled_denom) if labeled_denom else None
    escalation_rate = (l2_or_ir / total) if total else 0.0
    customer_notify_rate = (notify_customer / total) if total else 0.0
    defer_rate = (deferred / total) if total else 0.0

    # "Mis-escalation" proxy: L2/IR decisions later marked FP
    mis_escalations = sum(
        1
        for e in labeled
        if str(e.get("escalation") or "") in ("L2", "IR") and e.get("outcome_true_positive") is False
    )
    mis_escalation_rate = (mis_escalations / l2_or_ir) if l2_or_ir else None

    playbooks = Counter(str(e.get("playbook_id") or "none") for e in events)

    return {
        "total_decisions": total,
        "actions": dict(actions),
        "escalations": dict(escalations),
        "outcomes_recorded": len(with_outcome_at),
        "outcomes_labeled": len(labeled),
        "outcome_coverage_rate": round(labeled_rate, 4),
        "outcome_stamp_rate": round(stamp_rate, 4),
        "true_positive": tp,
        "false_positive": fp,
        "outcome_unknown": unknown_stamp,
        "fp_rate": round(fp_rate, 4) if fp_rate is not None else None,
        "escalation_rate": round(escalation_rate, 4),
        "mis_escalation_count": mis_escalations,
        "mis_escalation_rate": round(mis_escalation_rate, 4) if mis_escalation_rate is not None else None,
        "customer_notify_rate": round(customer_notify_rate, 4),
        "defer_rate": round(defer_rate, 4),
        "isolation_advisory_count": isolate_advisory,
        "playbooks": dict(playbooks.most_common(20)),
        "go_no_go_hints": _go_no_go_hints(
            total=total,
            outcome_rate=labeled_rate,
            mis_escalation_rate=mis_escalation_rate,
            defer_rate=defer_rate,
            fp_rate=fp_rate,
            unknown_stamps=unknown_stamp,
        ),
    }


def _go_no_go_hints(
    *,
    total: int,
    outcome_rate: float,
    mis_escalation_rate: float | None,
    defer_rate: float,
    fp_rate: float | None,
    unknown_stamps: int = 0,
) -> list[str]:
    hints: list[str] = []
    if total < 20:
        hints.append("Sample size < 20 — run closer to 8 weeks before Go/No-Go.")
    if outcome_rate < 0.3:
        hints.append(
            "Labeled outcome coverage (TP/FP) < 30% — set Jira resolution tag "
            "(False Positive / True Positive / Benign) or use decision-outcome."
        )
    if unknown_stamps > 0 and outcome_rate < 0.3:
        hints.append(
            f"{unknown_stamps} resolved tickets stamped without TP/FP — "
            "resolution tag not mapped or missing."
        )
    if mis_escalation_rate is not None and mis_escalation_rate <= 0.2 and outcome_rate >= 0.3:
        hints.append("Mis-escalation rate ≤ 20% — supports continue to v0.3 Knowledge.")
    if mis_escalation_rate is not None and mis_escalation_rate > 0.4:
        hints.append("Mis-escalation rate > 40% — tune rules before external pilot.")
    if defer_rate >= 0.1:
        hints.append(f"Defer/suppress rate {defer_rate:.0%} — noise reduction signal present.")
    if fp_rate is not None and fp_rate > 0.5:
        hints.append("FP rate among labeled outcomes > 50% — revisit customer notify thresholds.")
    if not hints:
        hints.append("Metrics look healthy enough for an internal Go decision.")
    return hints


def build_pilot_report(
    store: DecisionStore,
    *,
    source_id: str | None = None,
    customer_code: str | None = None,
    since: str | None = None,
    until: str | None = None,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = store.list_events(
        source_id=source_id,
        customer_code=customer_code,
        since=since,
        until=until,
        limit=5000,
    )
    metrics = compute_decision_metrics(events)
    unlabeled_resolved = [
        {
            "jira_key": e.get("jira_key"),
            "stellar_case_id": e.get("stellar_case_id"),
            "escalation": e.get("escalation"),
            "playbook_id": e.get("playbook_id"),
            "outcome_at": e.get("outcome_at"),
            "outcome_notes": e.get("outcome_notes"),
        }
        for e in events
        if e.get("outcome_at")
        and e.get("outcome_true_positive") is None
        and str(e.get("jira_key") or "").strip()
    ][:40]
    metrics["unlabeled_resolved_count"] = len(
        [
            e
            for e in events
            if e.get("outcome_at") and e.get("outcome_true_positive") is None
        ]
    )
    delta: dict[str, Any] = {}
    if isinstance(baseline, dict) and baseline:
        for key in (
            "mis_escalation_rate",
            "customer_notify_rate",
            "defer_rate",
            "fp_rate",
            "escalation_rate",
        ):
            cur = metrics.get(key)
            base = baseline.get(key)
            if cur is not None and base is not None:
                try:
                    # improvement: drop in mis-escalation / fp is positive
                    if key in ("mis_escalation_rate", "fp_rate", "escalation_rate", "customer_notify_rate"):
                        # for notify, "early/late" isn't signed; report relative change
                        delta[key] = round(float(cur) - float(base), 4)
                    else:
                        delta[key] = round(float(cur) - float(base), 4)
                except (TypeError, ValueError):
                    pass
        # ROI targets from plan: ≥20% improvement on mis-escalation (reduction)
        improvements: dict[str, Any] = {}
        if baseline.get("mis_escalation_rate") is not None and metrics.get("mis_escalation_rate") is not None:
            b = float(baseline["mis_escalation_rate"])
            c = float(metrics["mis_escalation_rate"])
            if b > 0:
                improvements["mis_escalation_reduction_pct"] = round((b - c) / b * 100.0, 2)
        metrics["baseline_delta"] = delta
        metrics["improvements"] = improvements

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "source_id": source_id,
            "customer_code": customer_code,
            "since": since,
            "until": until,
        },
        "metrics": metrics,
        "unlabeled_resolved": unlabeled_resolved,
        "sample_events": [
            {
                "event_id": e.get("event_id"),
                "stellar_case_id": e.get("stellar_case_id"),
                "jira_key": e.get("jira_key"),
                "action": e.get("action"),
                "escalation": e.get("escalation"),
                "playbook_id": e.get("playbook_id"),
                "notify_customer": e.get("notify_customer"),
                "outcome_true_positive": e.get("outcome_true_positive"),
                "outcome_root_cause": e.get("outcome_root_cause"),
                "created_at": e.get("created_at"),
            }
            for e in events[:25]
        ],
    }


def write_pilot_report(
    report: dict[str, Any],
    *,
    out_path: Path,
    fmt: str = "json",
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        text = render_pilot_markdown(report)
        out_path.write_text(text, encoding="utf-8")
    else:
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def render_pilot_markdown(report: dict[str, Any]) -> str:
    m = report.get("metrics") or {}
    lines = [
        "# AIxSOC Decision Intelligence — Pilot Audit Report",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Filters: `{json.dumps(report.get('filters') or {}, ensure_ascii=False)}`",
        "",
        "## Summary metrics",
        "",
        f"- Total decisions: **{m.get('total_decisions', 0)}**",
        f"- Outcome coverage (TP/FP labeled): **{m.get('outcome_coverage_rate')}**",
        f"- Outcome stamps (any writeback): **{m.get('outcome_stamp_rate')}** "
        f"({m.get('outcomes_recorded')} rows; labeled={m.get('outcomes_labeled')})",
        f"- Escalation rate (L2/IR): **{m.get('escalation_rate')}**",
        f"- Mis-escalation rate: **{m.get('mis_escalation_rate')}**",
        f"- Customer notify rate: **{m.get('customer_notify_rate')}**",
        f"- Defer/suppress rate: **{m.get('defer_rate')}**",
        f"- FP rate (among labeled outcomes): **{m.get('fp_rate')}**",
        "",
        "### Actions",
        "",
        "```",
        json.dumps(m.get("actions") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "### Escalations",
        "",
        "```",
        json.dumps(m.get("escalations") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "### Go / No-Go hints",
        "",
    ]
    for hint in m.get("go_no_go_hints") or []:
        lines.append(f"- {hint}")
    if m.get("improvements"):
        lines.extend(["", "### vs baseline", "", "```", json.dumps(m["improvements"], indent=2), "```"])
    unlabeled = report.get("unlabeled_resolved") or []
    if unlabeled:
        lines.extend(
            [
                "",
                f"## Unlabeled resolved tickets ({m.get('unlabeled_resolved_count', len(unlabeled))})",
                "",
                "Set Jira Resolution tag (True Positive / False Positive / Benign), then:",
                "`./Tools/run decision-outcome-backfill --apply`",
                "",
            ]
        )
        for u in unlabeled:
            lines.append(
                f"- `{u.get('jira_key')}` esc={u.get('escalation')} "
                f"pb={u.get('playbook_id')} outcome_at={u.get('outcome_at')}"
            )
    lines.extend(["", "## Sample events (latest 25)", ""])
    for e in report.get("sample_events") or []:
        lines.append(
            f"- `{e.get('created_at')}` {e.get('jira_key') or '-'} "
            f"action={e.get('action')} esc={e.get('escalation')} "
            f"tp={e.get('outcome_true_positive')} pb={e.get('playbook_id')}"
        )
    lines.append("")
    return "\n".join(lines)
