#!/usr/bin/env python3
"""Evaluate Decision Layer for a Stellar case (dry preview; optional persist)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.decision.pipeline import evaluate_case_decision, get_decision_store  # noqa: E402
from app.stellar.client import StellarClient  # noqa: E402


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Preview AIxSOC Decision Layer for one case")
    parser.add_argument("--case-id", required=True, help="Stellar case _id")
    parser.add_argument("--customer-code", default="", help="Override customer code")
    parser.add_argument("--persist", action="store_true", help="Write decision_events row")
    parser.add_argument("--ai", action="store_true", help="Also call SOC notify AI (needs API key)")
    args = parser.parse_args()

    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    if not st.stellar_base_url or not st.stellar_api_key:
        print("Set STELLAR_BASE_URL and STELLAR_API_KEY", file=sys.stderr)
        return 2

    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"
    store = get_decision_store(ROOT / st.stellar_sync_state_db) if args.persist else None

    async with StellarClient(
        base_url=str(st.stellar_base_url).rstrip("/"),
        api_key=st.stellar_api_key or "",
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
        http_max_retries=st.stellar_http_max_retries,
    ) as client:
        bundle = await client.fetch_case_bundle(args.case_id.strip())
        case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
        if not case:
            raw = await client.get_case(args.case_id.strip())
            case = StellarClient.extract_case_one(raw) or {}
        if not case:
            print(json.dumps({"ok": False, "error": "case not found"}, ensure_ascii=False))
            return 1

        from app.stellar.tenant_code import customer_code_from_case

        cc = (args.customer_code or "").strip() or customer_code_from_case(
            case, default=st.stellar_default_customer_code
        )
        decision = await evaluate_case_decision(
            case=case,
            bundle=bundle,
            source_id=source_id,
            customer_code=cc,
            store=store,
            run_ai=bool(args.ai),
            persist=bool(args.persist),
        )

    print(json.dumps({"ok": True, "decision": decision.to_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
