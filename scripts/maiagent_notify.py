#!/usr/bin/env python3
"""Manually run MaiAgent personal dual-track notify (does not change Groq SOC notify).

Examples:
  ./Tools/run maiagent-notify --ticket 1214
  ./Tools/run maiagent-notify --case-id 6a5495d9718e6a0aafacdefe --jira-key AIXSOC-xx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_notify_settings, get_stellar_settings  # noqa: E402
from app.notify.maiagent_personal import notify_maiagent_personal  # noqa: E402
from app.stellar.client import StellarClient  # noqa: E402
from app.stellar.tenant_code import customer_code_from_case  # noqa: E402


async def _resolve(client: StellarClient, *, case_id: str, ticket_id: int | None) -> str:
    cid = str(case_id or "").strip()
    if cid:
        return cid
    if ticket_id is None:
        return ""
    try:
        raw = await client.list_cases(limit=20, search=str(ticket_id))
        for c in StellarClient.extract_cases_list(raw):
            if c.get("ticket_id") == ticket_id or str(c.get("ticket_id")) == str(ticket_id):
                return str(c.get("_id") or "")
    except Exception:
        pass
    for skip in range(0, 500, 50):
        raw = await client.list_cases(limit=50, skip=skip, sort="modified_at", order="desc")
        for c in StellarClient.extract_cases_list(raw):
            if c.get("ticket_id") == ticket_id or str(c.get("ticket_id")) == str(ticket_id):
                return str(c.get("_id") or "")
    return ""


async def main() -> int:
    p = argparse.ArgumentParser(description="MaiAgent personal notify (SOC Groq path untouched)")
    p.add_argument("--ticket", type=int, default=None)
    p.add_argument("--case-id", default="")
    p.add_argument("--jira-key", default="", help="Subject label; default MAIAGENT-TEST-{ticket}")
    p.add_argument("--sync", action="store_true", help="Force await (ignore MAIAGENT_NOTIFY_ASYNC)")
    args = p.parse_args()

    get_stellar_settings.cache_clear()
    get_notify_settings.cache_clear()
    st = get_stellar_settings()
    ns = get_notify_settings()
    if not ns.maiagent_notify_enabled and not (ns.maiagent_api_key or "").strip():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "Set MAIAGENT_NOTIFY_ENABLED=true and MAIAGENT_* + personal recipients",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    async with StellarClient(
        base_url=str(st.stellar_base_url).rstrip("/"),
        api_key=st.stellar_api_key or "",
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
        http_max_retries=st.stellar_http_max_retries,
    ) as client:
        cid = await _resolve(client, case_id=args.case_id, ticket_id=args.ticket)
        if not cid:
            print(json.dumps({"ok": False, "error": "resolve_case_id_failed"}, indent=2))
            return 1
        bundle = await client.fetch_case_bundle(cid)
        case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}

    jira_key = (args.jira_key or "").strip() or f"MAIAGENT-TEST-{args.ticket or cid[:8]}"
    # CLI always awaits so you see the delivery result
    result = await notify_maiagent_personal(
        jira_key=jira_key,
        case_id=str(case.get("ticket_id") or cid),
        customer_code=customer_code_from_case(case) if case else "",
        stellar_case=case,
        stellar_bundle=bundle,
        settings=ns,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("sent") or result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
