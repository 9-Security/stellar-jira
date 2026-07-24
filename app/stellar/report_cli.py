"""Shared CLI flags for multi-tenant Stellar report export."""

from __future__ import annotations

import argparse
from datetime import date

from app.dates import parse_iso_date, parse_month
from app.stellar.tenant_model import StellarTenant
from app.stellar.tenants import resolve_report_tenant


def add_product_arg(parser: argparse.ArgumentParser, *, default: str = "darktrace") -> None:
    parser.add_argument(
        "--product",
        default=default,
        choices=("darktrace", "cortex"),
        help="Report product: darktrace | cortex (default: darktrace)",
    )


def add_tenant_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("tenant (multi-tenant)")
    group.add_argument(
        "--tenant",
        metavar="SOURCE_ID",
        help="Tenant source_id from config/stellar_tenants.json",
    )
    group.add_argument("--tenant-id", metavar="ID", help="Stellar API tenant_id")
    group.add_argument("--tenant-name", metavar="NAME", help="Filter by case tenant_name")
    group.add_argument("--customer-code", metavar="CODE", help="Customer code (2–16 alphanumeric)")


def add_monthly_period_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--month", metavar="YYYY-MM", help="Calendar month (inclusive)")
    group.add_argument("--date", metavar="YYYY-MM-DD", help="Single day (inclusive)")
    group.add_argument("--start", metavar="YYYY-MM-DD", help="Range start (requires --end)")
    parser.add_argument("--end", metavar="YYYY-MM-DD", help="Range end (requires --start)")


def add_export_period_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--month", metavar="YYYY-MM", help="Calendar month (inclusive)")
    group.add_argument("--since-date", metavar="YYYY-MM-DD", help="Inclusive start date")
    parser.add_argument("--until-date", metavar="YYYY-MM-DD", help="Inclusive end date (with --since-date)")


def resolve_monthly_period(args: argparse.Namespace) -> tuple[date, date]:
    if getattr(args, "month", None):
        return parse_month(args.month)
    if getattr(args, "date", None):
        d = parse_iso_date(args.date)
        return d, d
    if args.start:
        if not args.end:
            raise ValueError("--end is required when using --start")
        start_d = parse_iso_date(args.start)
        end_d = parse_iso_date(args.end)
        if end_d < start_d:
            raise ValueError("end must be on or after start")
        return start_d, end_d
    raise ValueError("Specify --month, --date, or --start/--end")


def resolve_export_period(args: argparse.Namespace) -> tuple[date | None, date | None]:
    if getattr(args, "month", None):
        return parse_month(args.month)
    since = getattr(args, "since_date", None)
    until = getattr(args, "until_date", None)
    if since or until:
        start_d = parse_iso_date(since) if since else None
        end_d = parse_iso_date(until) if until else None
        if start_d and end_d and end_d < start_d:
            raise ValueError("until-date must be on or after since-date")
        return start_d, end_d
    return None, None


def resolve_tenant_from_args(args: argparse.Namespace, tenants: list[StellarTenant]) -> StellarTenant:
    return resolve_report_tenant(
        tenants,
        source_id=getattr(args, "tenant", None),
        tenant_id=getattr(args, "tenant_id", None),
        tenant_name=getattr(args, "tenant_name", None),
        customer_code=getattr(args, "customer_code", None),
    )


def validate_product(tenant: StellarTenant, product: str) -> str:
    p = product.strip().lower()
    if not tenant.supports_product(p):
        raise ValueError(
            f"Tenant {tenant.source_id!r} does not support product {p!r}; "
            f"enabled: {tenant.products}"
        )
    return p
