#!/usr/bin/env python3
"""Backfill Decision outcomes from linked Jira issues (resolution tag → TP/FP)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_jira_settings, get_stellar_settings  # noqa: E402
from app.decision.outcome import apply_outcome_from_jira, infer_outcome_from_jira_fields  # noqa: E402
from app.decision.pipeline import get_decision_store  # noqa: E402
from app.jira.client import JiraClient  # noqa: E402
from app.sync.state import SyncState  # noqa: E402

_TERMINAL = frozenset(
    {"done", "resolved", "closed", "cancelled", "canceled", "complete", "completed"}
)


async def _run(*, dry_run: bool, jira_key: str) -> dict:
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    st = get_stellar_settings()
    js = get_jira_settings()
    store = get_decision_store(ROOT / st.stellar_sync_state_db)
    state = SyncState(ROOT / st.stellar_sync_state_db)
    state.init()
    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"

    linked = state.list_linked_jira_keys(source_id)
    if jira_key:
        linked = [(cid, jk) for cid, jk in linked if jk == jira_key]
        if not linked:
            row = store.get_latest_by_jira_key(jira_key)
            if row:
                linked = [(str(row.get("stellar_case_id") or ""), jira_key)]

    fields_need = ["status", "resolution", "description"]
    tag_field = (st.stellar_jira_resolution_tag_field or "").strip()
    if tag_field:
        fields_need.append(tag_field)

    results: list[dict] = []
    labeled = 0
    skipped = 0
    async with JiraClient(js) as jira:
        for case_id, jk in linked:
            issue = await jira.get_issue(jk, fields=fields_need)
            fields = (issue or {}).get("fields") or {}
            status_raw = fields.get("status")
            status_name = ""
            if isinstance(status_raw, dict):
                status_name = str(status_raw.get("name") or "").strip().lower()
            if status_name not in _TERMINAL:
                skipped += 1
                results.append(
                    {
                        "jira_key": jk,
                        "case_id": case_id,
                        "skipped": True,
                        "reason": f"non_terminal:{status_name or '?'}",
                    }
                )
                continue
            if dry_run:
                inferred = infer_outcome_from_jira_fields(
                    fields, tag_map_path=st.stellar_resolution_tag_map_path
                )
                row = {
                    "jira_key": jk,
                    "case_id": case_id,
                    "dry_run": True,
                    "status": status_name,
                    **inferred,
                }
                if inferred.get("true_positive") is not None:
                    labeled += 1
                results.append(row)
                continue
            outcome = apply_outcome_from_jira(
                store,
                jira_key=jk,
                fields=fields,
                source_id=source_id,
                stellar_case_id=case_id,
                tag_map_path=st.stellar_resolution_tag_map_path,
            )
            if outcome.get("true_positive") is not None:
                labeled += 1
            results.append(outcome)

    return {
        "ok": True,
        "dry_run": dry_run,
        "checked": len(results),
        "labeled_signal": labeled,
        "skipped_non_terminal": skipped,
        "results": results,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Backfill decision_events outcomes from Jira resolution tags"
    )
    p.add_argument("--apply", action="store_true", help="Write outcomes (default dry-run)")
    p.add_argument("--jira-key", default="", help="Only one issue")
    args = p.parse_args()
    out = asyncio.run(_run(dry_run=not args.apply, jira_key=str(args.jira_key or "").strip()))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
