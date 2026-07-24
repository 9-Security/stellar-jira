#!/usr/bin/env python3
"""Record decision outcome (TP/FP/root cause) for Dataset feedback loop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.decision.pipeline import get_decision_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Record Decision Dataset outcome")
    parser.add_argument("--jira-key", default="", help="Jira issue key")
    parser.add_argument("--event-id", default="", help="decision_events.event_id")
    parser.add_argument("--case-id", default="", help="Stellar case id")
    parser.add_argument("--true-positive", choices=("true", "false", "unknown"), default="unknown")
    parser.add_argument("--root-cause", default="", help="Final root cause text")
    parser.add_argument("--notes", default="")
    parser.add_argument("--source", default="manual")
    args = parser.parse_args()

    if not args.jira_key and not args.event_id and not args.case_id:
        print("Need --jira-key and/or --event-id and/or --case-id", file=sys.stderr)
        return 2

    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    store = get_decision_store(ROOT / st.stellar_sync_state_db)
    tp: bool | None
    if args.true_positive == "true":
        tp = True
    elif args.true_positive == "false":
        tp = False
    else:
        tp = None

    ok = store.record_outcome(
        event_id=args.event_id or None,
        jira_key=args.jira_key,
        source_id=(st.stellar_poll_source_id or "stellar"),
        stellar_case_id=args.case_id,
        true_positive=tp,
        root_cause=args.root_cause,
        notes=args.notes,
        source=args.source,
    )
    print(json.dumps({"ok": ok, "updated": ok}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
