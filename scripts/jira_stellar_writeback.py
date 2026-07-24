#!/usr/bin/env python3
"""Jira → Stellar: fields (assignee, status, severity, resolution tag) and/or comments."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.stellar.writeback import apply_jira_to_stellar_writeback  # noqa: E402


async def main() -> int:
    p = argparse.ArgumentParser(description="Jira → Stellar write-back")
    p.add_argument("--issue-key", required=True, help="Jira key, e.g. AIXSOC-3")
    p.add_argument("--case-id", default=None, help="Override Stellar _id")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fields-only", action="store_true", help="Skip comment sync")
    p.add_argument("--comment-only", action="store_true", help="Only sync comment")
    p.add_argument("--comment-id", default=None, help="Jira comment id from webhook")
    p.add_argument("--comment-text", default=None, help="Comment body override")
    p.add_argument("--severity", default=None)
    p.add_argument("--status", default=None)
    p.add_argument("--assignee", default=None, help="Assignee email override")
    p.add_argument("--resolution-tag", default=None, help="e.g. True Positive, None")
    args = p.parse_args()

    if args.fields_only and args.comment_only:
        p.error("use at most one of --fields-only and --comment-only")

    overrides: dict[str, str] = {}
    if args.severity:
        overrides["severity"] = args.severity
    if args.status:
        overrides["status"] = args.status
    if args.assignee:
        overrides["assignee"] = args.assignee
    if args.resolution_tag:
        overrides["resolution_tag"] = args.resolution_tag

    sync_fields = not args.comment_only
    want_comment = bool(args.comment_id or args.comment_text)
    if args.fields_only:
        want_comment = False

    out = await apply_jira_to_stellar_writeback(
        issue_key=args.issue_key,
        stellar_case_id=args.case_id,
        field_overrides=overrides or None,
        dry_run=args.dry_run,
        sync_fields=sync_fields,
        jira_comment_id=args.comment_id,
        comment_text=args.comment_text,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
