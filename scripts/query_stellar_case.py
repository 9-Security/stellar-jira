#!/usr/bin/env python3
"""Query one Stellar Cyber case (list latest or GET by internal _id). Prints JSON; no secrets."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.stellar.client import StellarAPIError, StellarClient  # noqa: E402

_SUMMARY_KEYS = (
    "_id",
    "ticket_id",
    "name",
    "status",
    "severity",
    "assignee",
    "assignee_name",
    "created_at",
    "modified_at",
    "tags",
    "cust_id",
    "tenant_name",
)


def _summary(case: dict) -> dict:
    return {k: case.get(k) for k in _SUMMARY_KEYS if k in case}


async def _run(*, case_id: str | None, limit: int, full: bool) -> int:
    get_stellar_settings.cache_clear()
    s = get_stellar_settings()
    if not s.stellar_base_url or not s.stellar_api_key:
        print(
            "Set STELLAR_BASE_URL and STELLAR_API_KEY in .env "
            "(API key from Stellar System | Users | API Keys).",
            file=sys.stderr,
        )
        if s.stellar_base_url and not s.stellar_api_key:
            print(
                "STELLAR_API_KEY is empty after loading .env — save the file in your editor "
                "(disk may still have STELLAR_API_KEY= with no value).",
                file=sys.stderr,
            )
        return 2

    base = str(s.stellar_base_url).rstrip("/")
    email = s.stellar_user_email or "(not set)"
    print(f"Stellar host: {base}")
    print(f"Service account (optional): {email}")
    if s.stellar_tenant_id:
        print(f"tenant_id filter: {s.stellar_tenant_id}")

    client = StellarClient(
        base_url=base,
        api_key=s.stellar_api_key,
        timeout_seconds=s.stellar_timeout_seconds,
        verify_tls=s.stellar_tls_verify,
        tenant_id=s.stellar_tenant_id,
    )
    try:
        async with client:
            if case_id:
                print(f"GET /cases/{case_id}")
                raw = await client.get_case(case_id)
            else:
                print(f"GET /cases?limit={limit}&sort=modified_at&order=desc")
                raw = await client.list_cases(limit=limit)
    except StellarAPIError as e:
        print(f"FAIL: {e} (http={e.status_code})", file=sys.stderr)
        if e.body is not None:
            print(json.dumps(e.body, indent=2, default=str)[:4000], file=sys.stderr)
        return 1

    if case_id:
        case = StellarClient.extract_case_one(raw)
        cases = [case] if case else []
    else:
        cases = StellarClient.extract_cases_list(raw)

    if not cases:
        print("No case returned (check tenant_id filter or RBAC).", file=sys.stderr)
        print(json.dumps(raw, indent=2, default=str)[:4000])
        return 1

    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        print(f"\n--- case [{i + 1}/{len(cases)}] summary ---")
        print(json.dumps(_summary(case), indent=2, default=str))
        if full:
            print(f"\n--- case [{i + 1}] full JSON ---")
            print(json.dumps(case, indent=2, default=str))

    if not case_id and cases and isinstance(cases[0], dict):
        cid = cases[0].get("_id")
        if cid:
            print(f"\nTip: re-run with --case-id {cid} for full detail from GET /cases/{{id}}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Query Stellar Cyber cases (JWT auth). Default: latest 1 case."
    )
    p.add_argument(
        "--case-id",
        help="Internal case _id from UI URL or list output (not ticket_id unless API accepts it)",
    )
    p.add_argument("--limit", type=int, default=1, help="When listing, number of cases (1-500)")
    p.add_argument("--full", action="store_true", help="Print full case JSON, not summary only")
    args = p.parse_args()
    return asyncio.run(_run(case_id=args.case_id, limit=max(1, min(args.limit, 500)), full=args.full))


if __name__ == "__main__":
    raise SystemExit(main())
