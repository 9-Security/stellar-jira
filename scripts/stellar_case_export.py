#!/usr/bin/env python3
"""Export full Stellar case bundle (case + all alerts + …) for offline / local AI agents.

Writes complete JSON (no stdout truncation). Sensitive — treat as confidential.

Examples:
  ./Tools/run stellar-case-export --ticket 1214 --out data/exports/case_1214.json
  ./Tools/run stellar-case-export --case-id 6a5495d9718e6a0aafacdefe --out data/exports/x.json --decision-meta
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.stellar.client import StellarAPIError, StellarClient  # noqa: E402
from app.stellar.cortex_fields import stellar_bundle_has_cortex_case_id  # noqa: E402
from app.stellar.response_action import (  # noqa: E402
    stellar_notify_disposition_label,
    stellar_response_action_text,
)
from app.stellar.tenant_code import customer_code_from_case  # noqa: E402


def _alert_docs(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = bundle.get("alerts")
    if not isinstance(alerts, dict):
        return []
    data = alerts.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    return [d for d in docs if isinstance(d, dict)]


def _action_histogram(docs: list[dict[str, Any]]) -> dict[str, int]:
    from collections import Counter

    from app.stellar.response_action import _response_action_from_alert_source

    ctr: Counter[str] = Counter()
    for doc in docs:
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        if not isinstance(src, dict):
            continue
        action = _response_action_from_alert_source(src) or "(empty)"
        ctr[action] += 1
    return dict(ctr.most_common())


async def _resolve_case_id(client: StellarClient, *, case_id: str, ticket_id: int | None) -> str:
    cid = str(case_id or "").strip()
    if cid:
        return cid
    if ticket_id is None:
        raise ValueError("Provide --case-id or --ticket")
    # Prefer search when supported
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
        if not StellarClient.extract_cases_list(raw):
            break
    raise ValueError(f"ticket_id={ticket_id} not found in recent cases list")


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Export full Stellar case+alerts JSON for local AI agentic analysis"
    )
    parser.add_argument("--case-id", default="", help="Stellar case _id")
    parser.add_argument("--ticket", type=int, default=None, help="Stellar ticket_id (e.g. 1214)")
    parser.add_argument(
        "--out",
        default="",
        help="Output JSON path (default: data/exports/stellar_case_<ticket_or_id>.json)",
    )
    parser.add_argument(
        "--decision-meta",
        action="store_true",
        help="Include Disposition + Decision preview (rules/knowledge; no LLM)",
    )
    parser.add_argument(
        "--include-comments",
        action="store_true",
        help="Also fetch case comments",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (0 = compact)")
    args = parser.parse_args()

    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    if not st.stellar_base_url or not st.stellar_api_key:
        print("Set STELLAR_BASE_URL and STELLAR_API_KEY in .env", file=sys.stderr)
        return 2

    async with StellarClient(
        base_url=str(st.stellar_base_url).rstrip("/"),
        api_key=st.stellar_api_key or "",
        timeout_seconds=max(120.0, float(st.stellar_timeout_seconds)),
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
        http_max_retries=st.stellar_http_max_retries,
    ) as client:
        try:
            cid = await _resolve_case_id(
                client, case_id=args.case_id, ticket_id=args.ticket
            )
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        if not cid:
            print("Could not resolve case id", file=sys.stderr)
            return 1

        try:
            bundle = await client.fetch_case_bundle(cid)
        except StellarAPIError as e:
            print(f"FAIL fetch bundle: {e}", file=sys.stderr)
            return 1

        if args.include_comments:
            try:
                bundle["comments"] = await client.get_case_comments(cid)
            except StellarAPIError as e:
                bundle["comments"] = {"error": str(e), "http_status": e.status_code}

        case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
        docs = _alert_docs(bundle)
        ticket = case.get("ticket_id")
        cc = customer_code_from_case(case, default=st.stellar_default_customer_code)

        meta: dict[str, Any] = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exporter": "stellar-case-export",
            "stellar_case_id": cid,
            "ticket_id": ticket,
            "customer_code": cc,
            "alert_count_in_bundle": len(docs),
            "case_size_field": case.get("size"),
            "has_cortex_case_id": stellar_bundle_has_cortex_case_id(bundle),
            "disposition": stellar_notify_disposition_label(bundle),
            "response_action": stellar_response_action_text(bundle),
            "action_histogram": _action_histogram(docs),
            "note": (
                "Full case+alerts for local AI. Treat as sensitive. "
                "action_histogram uses API action/action_pretty; Cortex case_id is separate."
            ),
        }

        if args.decision_meta:
            try:
                from app.decision.pipeline import evaluate_case_decision

                decision = await evaluate_case_decision(
                    case=case,
                    bundle=bundle,
                    source_id=(st.stellar_poll_source_id or "stellar").strip() or "stellar",
                    customer_code=cc,
                    middleware_case_id="",
                    run_ai=False,
                    persist=False,
                )
                meta["decision_preview"] = {
                    "action": decision.action,
                    "escalation": decision.escalation,
                    "playbook_id": decision.playbook_id,
                    "isolate_host": decision.isolate_host,
                    "notify_customer": decision.notify_customer,
                    "confidence": decision.confidence,
                    "rule_hits": decision.rule_hits,
                    "knowledge_hits": decision.knowledge_hits,
                    "summary": decision.summary,
                    "jira_labels": decision.jira_labels,
                    "jira_priority": decision.jira_priority,
                }
                gate = bool(
                    getattr(st, "decision_only_without_cortex_case_id", True)
                    and stellar_bundle_has_cortex_case_id(bundle)
                )
                meta["decision_would_run_on_create"] = not gate
            except Exception as e:
                meta["decision_preview_error"] = str(e)

        payload = {
            "meta": meta,
            "bundle": bundle,
        }

    out = Path(args.out.strip()) if str(args.out or "").strip() else None
    if out is None:
        label = str(ticket) if ticket is not None else cid
        out = ROOT / "data" / "exports" / f"stellar_case_{label}.json"
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    indent = None if int(args.indent) <= 0 else int(args.indent)
    text = json.dumps(payload, ensure_ascii=False, indent=indent, default=str)
    out.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out),
                "bytes": len(text.encode("utf-8")),
                "stellar_case_id": cid,
                "ticket_id": ticket,
                "alert_count": len(docs),
                "has_cortex_case_id": meta["has_cortex_case_id"],
                "disposition": meta["disposition"],
                "action_histogram": meta["action_histogram"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
