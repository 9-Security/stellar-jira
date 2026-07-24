#!/usr/bin/env python3
"""Fetch Stellar case bundle: case + alerts + observables + activities + summary."""

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


async def _run(case_id: str | None) -> int:
    get_stellar_settings.cache_clear()
    s = get_stellar_settings()
    if not s.stellar_base_url or not s.stellar_api_key:
        print("Set STELLAR_* in .env", file=sys.stderr)
        return 2
    base = str(s.stellar_base_url).rstrip("/")
    async with StellarClient(
        base_url=base,
        api_key=s.stellar_api_key,
        timeout_seconds=s.stellar_timeout_seconds,
        verify_tls=s.stellar_tls_verify,
        tenant_id=s.stellar_tenant_id,
    ) as client:
        try:
            if not case_id:
                listed = await client.list_cases(limit=1)
                cases = StellarClient.extract_cases_list(listed)
                if not cases:
                    print("No cases.", file=sys.stderr)
                    return 1
                case_id = str(cases[0].get("_id") or "")
            bundle = await client.fetch_case_bundle(case_id)
        except StellarAPIError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 1
    print(json.dumps(bundle, indent=2, default=str)[:120000])
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Stellar case detail bundle (JSON)")
    p.add_argument("--case-id", help="Stellar _id")
    args = p.parse_args()
    return asyncio.run(_run(args.case_id))


if __name__ == "__main__":
    raise SystemExit(main())
