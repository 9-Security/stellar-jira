#!/usr/bin/env python3
"""Stellar Cyber Darktrace events report (multi-tenant CSV/JSON)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.stellar.report_cli import (  # noqa: E402
    add_export_period_args,
    add_product_arg,
    add_tenant_args,
    resolve_export_period,
    resolve_tenant_from_args,
    validate_product,
)
from app.stellar.report_runner import load_tenants_for_repo, resolve_out_dir, run_product_export  # noqa: E402

REPO_ROOT = ROOT
DEFAULT_OUT_DIR = REPO_ROOT / "reports"


async def _run(args: argparse.Namespace) -> int:
    try:
        since_date, until_date = resolve_export_period(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        print(f"Unknown IANA timezone: {args.timezone}", file=sys.stderr)
        return 2

    tenants = load_tenants_for_repo(REPO_ROOT)
    try:
        tenant = resolve_tenant_from_args(args, tenants)
        product = validate_product(tenant, args.product)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    out_dir = resolve_out_dir(REPO_ROOT, args.out_dir, DEFAULT_OUT_DIR)
    try:
        result = await run_product_export(
            repo_root=REPO_ROOT,
            tenant=tenant,
            product=product,
            since_date=since_date,
            until_date=until_date,
            timezone_name=args.timezone,
            out_dir=out_dir,
            fmt=args.format,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Stellar events (Darktrace or Cortex XDR) as CSV/JSON export."
    )
    add_tenant_args(parser)
    add_product_arg(parser)
    add_export_period_args(parser)
    parser.add_argument("--timezone", default="Asia/Taipei", help="Display timezone (default Asia/Taipei)")
    parser.add_argument("--out-dir", help=f"Output directory (default {DEFAULT_OUT_DIR.relative_to(REPO_ROOT)})")
    parser.add_argument(
        "--format",
        choices=("csv", "json", "both"),
        default="both",
        help="Output format (default both)",
    )
    parser.add_argument("--page-size", type=int, default=500, help="Cases API page size (max 500)")
    parser.add_argument("--max-pages", type=int, default=200, help="Max case list pages")
    args = parser.parse_args()
    if args.since_date and not args.until_date:
        parser.error("--until-date is required when using --since-date")
    if args.until_date and not args.since_date:
        parser.error("--since-date is required when using --until-date")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
