#!/usr/bin/env python3
"""Generate Decision Intelligence pilot audit / ROI report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.decision.pipeline import get_decision_store  # noqa: E402
from app.decision.report import build_pilot_report, write_pilot_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="AIxSOC Decision pilot audit report")
    parser.add_argument("--customer-code", default="")
    parser.add_argument("--since", default="")
    parser.add_argument("--until", default="")
    parser.add_argument("--baseline", default="", help="JSON file with baseline metrics")
    parser.add_argument("--out", default="data/decision_pilot_report.md")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    args = parser.parse_args()

    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    store = get_decision_store(ROOT / st.stellar_sync_state_db)

    baseline = None
    if args.baseline:
        bp = Path(args.baseline)
        if not bp.is_absolute():
            bp = ROOT / bp
        baseline = json.loads(bp.read_text(encoding="utf-8"))
        if isinstance(baseline, dict) and "metrics" in baseline:
            baseline = baseline["metrics"]

    report = build_pilot_report(
        store,
        source_id=(st.stellar_poll_source_id or "stellar"),
        customer_code=args.customer_code or None,
        since=args.since or None,
        until=args.until or None,
        baseline=baseline,
    )
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    write_pilot_report(report, out_path=out, fmt=args.format)
    # Always print JSON summary to stdout for automation
    print(json.dumps({"ok": True, "out": str(out), "metrics": report.get("metrics")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
