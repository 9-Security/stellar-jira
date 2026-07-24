#!/usr/bin/env python3
"""Stellar Cyber Darktrace monthly Word report (multi-tenant)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.stellar.report_cli import (  # noqa: E402
    add_monthly_period_args,
    add_product_arg,
    add_tenant_args,
    resolve_monthly_period,
    resolve_tenant_from_args,
    validate_product,
)
from app.stellar.report_runner import load_tenants_for_repo, resolve_out_dir, run_product_monthly  # noqa: E402

REPO_ROOT = ROOT
DEFAULT_OUT_DIR = REPO_ROOT / "reports"


async def _async_main(args: argparse.Namespace) -> int:
    try:
        start_d, end_d = resolve_monthly_period(args)
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

    out_dir = resolve_out_dir(REPO_ROOT, args.output_dir, DEFAULT_OUT_DIR)
    logo_path = Path(args.logo).expanduser() if args.logo else None
    if logo_path and not logo_path.is_absolute():
        logo_path = REPO_ROOT / logo_path

    try:
        out_docx = await run_product_monthly(
            repo_root=REPO_ROOT,
            tenant=tenant,
            product=product,
            start_d=start_d,
            end_d=end_d,
            timezone_name=args.timezone,
            out_dir=out_dir,
            logo_path=logo_path,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    size_kb = out_docx.stat().st_size / 1024.0 if out_docx.is_file() else 0.0
    print(f"WROTE {out_docx} ({size_kb:.1f} KiB)")
    print(f"Report output directory: {out_docx.parent}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="產生 Stellar 月報 Word（多租戶：--tenant + --product darktrace|cortex + --month）"
    )
    add_tenant_args(parser)
    add_product_arg(parser)
    add_monthly_period_args(parser)
    parser.add_argument("--timezone", default="Asia/Taipei", help="時區（預設 Asia/Taipei）")
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help=f"輸出目錄（預設 {DEFAULT_OUT_DIR.relative_to(REPO_ROOT)}）",
    )
    parser.add_argument("--logo", metavar="PATH", default=None, help="底圖 Logo（全頁浮水印）")
    parser.add_argument("--page-size", type=int, default=500, help="Cases API 分頁大小")
    parser.add_argument("--max-pages", type=int, default=200, help="Cases 列表最大頁數")
    args = parser.parse_args()
    if args.start and not args.end:
        parser.error("--end is required when using --start")
    if args.end and not args.start:
        parser.error("--start is required when using --end")
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
