#!/usr/bin/env python3
"""Export Decision Dataset (JSONL) with joined Stellar case snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.decision.pipeline import get_decision_store  # noqa: E402
from app.sync.case_snapshots import get_case_snapshot_store  # noqa: E402


def _snapshot_for_event(
    event: dict,
    *,
    snapshots,
    source_id: str,
) -> dict | None:
    sid = str(event.get("snapshot_id") or "").strip()
    row = snapshots.get_by_id(sid) if sid else None
    if row is None:
        row = snapshots.get_latest(source_id, str(event.get("stellar_case_id") or ""))
    if not row:
        return None
    bundle = snapshots.load_bundle_payload(row)
    case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
    return {
        "snapshot_id": row.get("snapshot_id"),
        "source": "Stellar Cyber",
        "stellar_case_id": row.get("stellar_case_id"),
        "modified_at_ms": row.get("modified_at_ms"),
        "captured_at": row.get("captured_at"),
        "storage_mode": row.get("storage_mode"),
        "bytes_size": row.get("bytes_size"),
        "case": case,
        "alerts": bundle.get("alerts"),
        "observables": bundle.get("observables"),
        "summary": bundle.get("summary"),
        "activities": bundle.get("activities"),
        "ai_summary": bundle.get("ai_summary"),
        "display_name": case.get("name") or case.get("display_name"),
        "severity": case.get("severity"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export decision_events + snapshots as JSONL Dataset")
    parser.add_argument("--out", default="data/decision_dataset.jsonl")
    parser.add_argument("--customer-code", default="")
    parser.add_argument("--since", default="", help="ISO timestamp lower bound")
    parser.add_argument("--until", default="", help="ISO timestamp upper bound")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--with-outcome-only", action="store_true")
    parser.add_argument("--without-snapshot", action="store_true", help="Skip snapshot join (legacy export)")
    args = parser.parse_args()

    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    db = ROOT / st.stellar_sync_state_db
    store = get_decision_store(db)
    snapshots = get_case_snapshot_store(db)
    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"

    events = store.list_events(
        source_id=source_id,
        customer_code=args.customer_code or None,
        since=args.since or None,
        until=args.until or None,
        limit=args.limit,
    )
    if args.with_outcome_only:
        events = [e for e in events if e.get("outcome_at")]

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for e in events:
            snap = None if args.without_snapshot else _snapshot_for_event(e, snapshots=snapshots, source_id=source_id)
            row = {
                "alert": snap
                or {
                    "source": "Stellar Cyber",
                    "stellar_case_id": e.get("stellar_case_id"),
                    "context": e.get("context") or {},
                },
                "customer": {"code": e.get("customer_code")},
                "decision": e.get("decision")
                or {
                    "action": e.get("action"),
                    "escalation": e.get("escalation"),
                    "notify_customer": e.get("notify_customer"),
                    "isolate_host": e.get("isolate_host"),
                    "playbook_id": e.get("playbook_id"),
                },
                "playbook": {"id": e.get("playbook_id")},
                "ai": e.get("ai_sections"),
                "outcome": {
                    "true_positive": e.get("outcome_true_positive"),
                    "root_cause": e.get("outcome_root_cause"),
                    "notes": e.get("outcome_notes"),
                    "at": e.get("outcome_at"),
                    "source": e.get("outcome_source"),
                },
                "meta": {
                    "event_id": e.get("event_id"),
                    "snapshot_id": e.get("snapshot_id") or (snap or {}).get("snapshot_id"),
                    "jira_key": e.get("jira_key"),
                    "middleware_case_id": e.get("middleware_case_id"),
                    "customer_code": e.get("customer_code"),
                    "created_at": e.get("created_at"),
                },
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {"ok": True, "count": len(events), "out": str(out), "snapshots_joined": not args.without_snapshot},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
