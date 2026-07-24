#!/usr/bin/env python3
"""Prune Stellar case snapshots to evidence milestones (keeps Decision evidence intact)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.sync.case_snapshots import REPO_ROOT, get_case_snapshot_store  # noqa: E402


def _orphan_archive_files(store) -> list[Path]:
    refs: set[Path] = set()
    for sid, cid in store.list_case_keys():
        for row in store.list_for_case(sid, cid, resolve_severity=False):
            if row.get("storage_mode") != "file" or not row.get("bundle_path"):
                continue
            path = Path(str(row["bundle_path"]))
            if not path.is_absolute():
                path = REPO_ROOT / path
            refs.add(path.resolve())
    st = get_stellar_settings()
    base = Path(st.case_archive_dir)
    if not base.is_absolute():
        base = REPO_ROOT / base
    if not base.is_dir():
        return []
    orphans: list[Path] = []
    for f in base.rglob("*.json"):
        try:
            if f.resolve() not in refs:
                orphans.append(f)
        except OSError:
            continue
    return orphans


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Garbage-collect stellar_case_snapshots: keep decision-referenced, "
            "earliest/latest, jira-linked, and first snapshot per severity. "
            "Default is dry-run. If case_archive files are root-owned, use sudo."
        )
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete non-milestone snapshots (and their case_archive files).",
    )
    p.add_argument(
        "--source-id",
        default="",
        help="Limit to one poll source_id (default: all).",
    )
    p.add_argument(
        "--case-id",
        default="",
        help="Limit to one stellar case _id.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable summary JSON.",
    )
    args = p.parse_args()
    dry_run = not args.apply

    get_stellar_settings.cache_clear()
    store = get_case_snapshot_store()
    source = str(args.source_id or "").strip() or None
    case_id = str(args.case_id or "").strip()

    if case_id:
        sid = source or get_stellar_settings().stellar_poll_source_id or "stellar"
        result: dict = {
            "cases": 1,
            "cases_with_drops": 0,
            "drop_total": 0,
            "deleted": 0,
            "drop_bytes": 0,
            "dry_run": dry_run,
            "protected_snapshot_ids": len(store.protected_snapshot_ids()),
            "plans": [],
        }
        plan = store.prune_case(sid, case_id, dry_run=dry_run)
        if plan["drop"]:
            result["cases_with_drops"] = 1
            result["plans"] = [plan]
        result["drop_total"] = int(plan["drop"])
        result["deleted"] = int(plan.get("deleted") or 0)
        result["drop_bytes"] = int(plan.get("drop_bytes") or 0)
    else:
        result = store.prune_all(source_id=source, dry_run=dry_run)

    orphans = _orphan_archive_files(store)
    orphan_bytes = sum(f.stat().st_size for f in orphans if f.is_file())
    result["orphan_files"] = len(orphans)
    result["orphan_bytes"] = orphan_bytes
    orphan_deleted = 0
    orphan_failed = 0
    if args.apply and orphans:
        for f in orphans:
            try:
                f.unlink()
                orphan_deleted += 1
            except OSError:
                orphan_failed += 1
        st = get_stellar_settings()
        base = Path(st.case_archive_dir)
        if not base.is_absolute():
            base = REPO_ROOT / base
        if base.is_dir():
            for d in sorted(base.rglob("*"), reverse=True):
                if d.is_dir():
                    try:
                        next(d.iterdir())
                    except StopIteration:
                        try:
                            d.rmdir()
                        except OSError:
                            pass
                    except OSError:
                        pass
    result["orphan_deleted"] = orphan_deleted
    result["orphan_failed"] = orphan_failed

    if args.json:
        slim = dict(result)
        slim_plans = []
        for plan in result.get("plans") or []:
            slim_plans.append(
                {
                    "source_id": plan["source_id"],
                    "stellar_case_id": plan["stellar_case_id"],
                    "total": plan["total"],
                    "keep": plan["keep"],
                    "drop": plan["drop"],
                    "drop_bytes": plan["drop_bytes"],
                    "deleted": plan.get("deleted", 0),
                }
            )
        slim["plans"] = slim_plans
        print(json.dumps(slim, ensure_ascii=False, indent=2))
    else:
        mode = "DRY-RUN" if dry_run else "APPLY"
        print(f"case-archive-gc [{mode}]")
        print(
            f"  cases={result['cases']} with_drops={result['cases_with_drops']} "
            f"drop={result['drop_total']} deleted={result['deleted']} "
            f"drop_bytes≈{result['drop_bytes']:,} "
            f"protected_decision_snapshots={result['protected_snapshot_ids']}"
        )
        for plan in (result.get("plans") or [])[:20]:
            print(
                f"  - {plan['stellar_case_id']}: {plan['total']}→keep {plan['keep']} "
                f"(drop {plan['drop']}, ≈{plan['drop_bytes']:,} B)"
            )
        if len(result.get("plans") or []) > 20:
            print(f"  … {len(result['plans']) - 20} more cases")
        print(
            f"  orphan_archive_files={result['orphan_files']} "
            f"(≈{result['orphan_bytes']:,} B) "
            f"deleted={result['orphan_deleted']} failed={result['orphan_failed']}"
        )
        if dry_run and (result["drop_total"] or result["orphan_files"]):
            print("Re-run with --apply to delete.")
            if result["orphan_files"]:
                print(
                    "If file deletes fail with Permission denied, use: "
                    "sudo ./Tools/run case-archive-gc --apply"
                )
        elif not dry_run:
            print(
                "Done. Consider: sqlite3 data/stellar_sync_state.sqlite 'VACUUM;' "
                "if DB file still large."
            )
            if result["orphan_failed"]:
                print(
                    f"WARNING: {result['orphan_failed']} archive files could not be deleted "
                    "(try sudo ./Tools/run case-archive-gc --apply)."
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
