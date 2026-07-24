"""Human-facing Jira notes for Decision Layer (create + optional outcome reminder)."""

from __future__ import annotations

from typing import Any

from app.decision.models import DecisionResult

OUTCOME_REMINDER_MARKER = "#aixsoc-outcome-reminder"
CREATE_COMMENT_MARKER = "#aixsoc-decision"

# Duty-first checklists (Traditional Chinese). Outcome/Dataset is intentionally secondary under path C.
_PLAYBOOK_CHECKLISTS: dict[str, list[str]] = {
    "PB-IR-MALWARE-BLOCKED": [
        "確認平台已阻擋（勿再建議重隔離）",
        "問使用者／客戶 IT：當時在做什麼、是否授權軟體／掃毒／維運",
        "保全主機／檔案／Cortex 相關紀錄；看有無橫向或其他主機同訊號",
        "若確認良性：註記原因後結案；若偏惡意：升 IR／客戶通知依程序",
    ],
    "PB-IR-MALWARE": [
        "先釐清，不要一上來隔離主機",
        "對照 Malware／WildFire 樣本與路徑；問使用者／IT 是否已知工具",
        "僅在 JSON／證據清楚為惡意時，才把隔離當後段建議（本票 isolation advisory）",
        "客戶通知若已開啟：先對齊對內敘事再對外",
    ],
    "PB-L2-HIGH": [
        "L2：釐清告警主軸（勿被 BIOC 雜訊帶跑）",
        "確認主機／帳號／時段；先問現場或 IT",
        "需要升 IR 或客戶通知時再升級，避免過早對外",
    ],
    "PB-L2-BLOCKED": [
        "已阻擋類：以「驗證阻擋＋釐清原因」為主，不重下同一阻擋",
        "問使用者／IT；保留證據後決定結案或升級",
    ],
    "PB-L1-MED": [
        "L1：先當一般調查；嚴重程度升高再升級",
    ],
    "PB-L1-PERSIST": [
        "Persistence／BIOC：多數需先釐清是否安裝程式或維運",
        "問使用者／IT；勿把「立即隔離」當首步",
    ],
    "PB-L1-EXEC": [
        "Execution：確認行程／檔案是否公司工具；先釐清再處置",
    ],
    "PB-DEFAULT": [
        "依 Description／告警摘要釐清；不確定先問現場或 IT",
    ],
}


def _as_decision_fields(decision: DecisionResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(decision, DecisionResult):
        d = decision
        return {
            "action": d.action,
            "escalation": d.escalation,
            "playbook_id": d.playbook_id or "",
            "isolate_host": bool(d.isolate_host),
            "notify_customer": bool(d.notify_customer),
            "confidence": d.confidence,
            "rule_hits": list(d.rule_hits),
            "knowledge_hits": list(d.knowledge_hits),
            "summary": d.summary or "",
        }
    return {
        "action": str(decision.get("action") or ""),
        "escalation": str(decision.get("escalation") or ""),
        "playbook_id": str(decision.get("playbook_id") or ""),
        "isolate_host": bool(decision.get("isolate_host")),
        "notify_customer": bool(decision.get("notify_customer")),
        "confidence": float(decision.get("confidence") or 0.0)
        if decision.get("confidence") is not None
        else 0.0,
        "rule_hits": [str(x) for x in (decision.get("rule_hits") or []) if str(x).strip()],
        "knowledge_hits": [str(x) for x in (decision.get("knowledge_hits") or []) if str(x).strip()],
        "summary": str(decision.get("summary") or ""),
    }


def _brief_case_facts(
    *,
    case: dict[str, Any] | None,
    bundle: dict[str, Any] | None,
) -> dict[str, str]:
    case = case if isinstance(case, dict) else {}
    bundle = bundle if isinstance(bundle, dict) else {}
    severity = str(case.get("severity") or "").strip()
    disposition = ""
    hosts: list[str] = []
    try:
        from app.stellar.response_action import stellar_notify_disposition_label

        disposition = stellar_notify_disposition_label(bundle) or ""
    except Exception:
        disposition = ""
    try:
        obs = bundle.get("observables")
        if isinstance(obs, dict):
            inner = obs.get("observables") if isinstance(obs.get("observables"), dict) else obs
            host_rows = inner.get("host") if isinstance(inner, dict) else None
            if isinstance(host_rows, list):
                for row in host_rows[:5]:
                    if not isinstance(row, dict):
                        continue
                    name = str(row.get("hostname") or row.get("name") or "").strip()
                    if name and name not in hosts:
                        hosts.append(name)
    except Exception:
        pass
    display = str(case.get("name") or "").strip()
    try:
        from app.stellar.case_display_name import stellar_case_display_name

        display = stellar_case_display_name(case, bundle) or display
    except Exception:
        pass
    return {
        "severity": severity,
        "disposition": disposition,
        "hosts": ", ".join(hosts) if hosts else "",
        "display_name": display[:120],
    }


def playbook_checklist(playbook_id: str) -> list[str]:
    pb = str(playbook_id or "").strip()
    if pb in _PLAYBOOK_CHECKLISTS:
        return list(_PLAYBOOK_CHECKLISTS[pb])
    if pb.startswith("PB-IR-"):
        return list(_PLAYBOOK_CHECKLISTS["PB-IR-MALWARE"])
    if pb.startswith("PB-L2-"):
        return list(_PLAYBOOK_CHECKLISTS["PB-L2-HIGH"])
    if pb.startswith("PB-L1-"):
        return list(_PLAYBOOK_CHECKLISTS["PB-L1-MED"])
    return list(_PLAYBOOK_CHECKLISTS["PB-DEFAULT"])


def format_decision_create_comment(
    decision: DecisionResult | dict[str, Any],
    *,
    middleware_case_id: str = "",
    case: dict[str, Any] | None = None,
    bundle: dict[str, Any] | None = None,
) -> str:
    """Duty handoff comment: what to do next (not Dataset/outcome nags)."""
    fields = _as_decision_fields(decision)
    facts = _brief_case_facts(case=case, bundle=bundle)
    mid = str(middleware_case_id or "").strip()
    pb = fields["playbook_id"] or "-"
    checklist = playbook_checklist(fields["playbook_id"])

    isolate_line = (
        "隔離建議：有（僅 Jira label，系統不會自動隔離）"
        if fields["isolate_host"]
        else "隔離建議：無（先釐清／驗證即可，不要先隔離）"
    )
    notify_line = (
        "客戶通知：建議開（對齊對內敘事後再對外）"
        if fields["notify_customer"]
        else "客戶通知：暫不建議"
    )

    lines: list[str | None] = [
        "AIxSOC Decision — 值班覆核／下手順序",
        f"案件編號: {mid}" if mid else None,
        f"告警: {facts['display_name']}" if facts.get("display_name") else None,
        f"嚴重程度: {facts['severity']}" if facts.get("severity") else None,
        f"處置狀態: {facts['disposition']}" if facts.get("disposition") else None,
        f"主機: {facts['hosts']}" if facts.get("hosts") else None,
        "",
        f"升級層級: {fields['escalation']}",
        f"Playbook: {pb}",
        isolate_line,
        notify_line,
        f"摘要: {fields['summary']}" if fields.get("summary") else None,
        "",
        "建議步驟：",
    ]
    for i, step in enumerate(checklist, 1):
        lines.append(f"{i}. {step}")
    lines.extend(
        [
            "",
            f"規則命中: {', '.join(fields['rule_hits'][:6]) or '-'}",
            f"知識命中: {', '.join(fields['knowledge_hits'][:6]) or '-'}",
            CREATE_COMMENT_MARKER,
        ]
    )
    return "\n".join(x for x in lines if x is not None)


def format_outcome_reminder_comment(*, jira_key: str = "") -> str:
    """Optional Dataset loop reminder (path B/outcome); disabled by default under path C."""
    key = str(jira_key or "").strip()
    prefix = f"{key}: " if key else ""
    return "\n".join(
        [
            f"{prefix}AIxSOC 提醒：此票已結案，但「resolution tag」尚未設成 True Positive / False Positive / Benign。",
            "請 Edit issue → 欄位 resolution tag 選擇其一；若畫面上沒有此欄位，請專案管理員加到 Edit/Resolve 畫面。",
            "暫時做法：在評論寫 False Positive 或 True Positive（可加 root cause: …），系統會從留言推 TP/FP。",
            OUTCOME_REMINDER_MARKER,
        ]
    )


def outcome_remind_meta_key(jira_key: str) -> str:
    return f"decision_outcome_remind:{str(jira_key or '').strip().upper()}"
