#!/usr/bin/env python3
"""Resend SOC notification for an existing Stellar case (no new Jira ticket)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_jira_settings, get_notify_settings, get_stellar_settings  # noqa: E402
from app.jira.client import JiraAPIError, JiraClient  # noqa: E402
from app.notify.ticket_created import notify_ticket_created  # noqa: E402
from app.stellar.client import StellarAPIError, StellarClient  # noqa: E402
from app.stellar.tenant_code import customer_code_from_case  # noqa: E402
from app.sync.state import PENDING_JIRA_KEY, SyncState  # noqa: E402


def _middleware_case_id_from_issue(issue: dict, field_id: str) -> str:
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return ""
    val = fields.get(field_id)
    if val is None:
        return ""
    return str(val).strip()


async def _run(*, stellar_case_id: str, jira_key_override: str | None) -> int:
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    get_notify_settings.cache_clear()

    st = get_stellar_settings()
    notify_st = get_notify_settings()
    if not notify_st.soc_notify_enabled:
        print("SOC_NOTIFY_ENABLED is false — set to true in .env", file=sys.stderr)
        return 2
    if not notify_st.is_configured:
        print("Notify incomplete — set RESEND_API_KEY (or SMTP_HOST) and SOC_NOTIFY_FROM", file=sys.stderr)
        return 2
    if not (notify_st.soc_notify_to or "").strip():
        print("Set SOC_NOTIFY_TO (comma-separated SOC emails)", file=sys.stderr)
        return 2
    if not st.stellar_base_url or not st.stellar_api_key:
        print("Set STELLAR_BASE_URL and STELLAR_API_KEY in .env", file=sys.stderr)
        return 2

    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"
    state = SyncState(ROOT / st.stellar_sync_state_db)
    state.init(legacy_source_id=source_id)

    jira_key = (jira_key_override or state.get_jira_key(source_id, stellar_case_id) or "").strip()
    if not jira_key or jira_key == PENDING_JIRA_KEY:
        print(
            f"No Jira key for Stellar case {stellar_case_id!r} in sync DB "
            f"(pass --jira-key if needed).",
            file=sys.stderr,
        )
        return 1

    base = str(st.stellar_base_url).rstrip("/")
    async with StellarClient(
        base_url=base,
        api_key=st.stellar_api_key,
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
    ) as client:
        try:
            bundle = await client.fetch_case_bundle(stellar_case_id)
        except StellarAPIError as e:
            print(f"Stellar error: {e}", file=sys.stderr)
            return 1

    case = bundle.get("case")
    if not isinstance(case, dict):
        print("Could not parse case from Stellar bundle.", file=sys.stderr)
        return 1

    try:
        customer_code = customer_code_from_case(case, default=st.stellar_default_customer_code)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2

    case_field = st.stellar_case_id_jira_field or "customfield_10060"
    middleware_case_id = ""
    jira_s = get_jira_settings()
    summary = str(case.get("name") or "").strip()
    if jira_s.jira_base_url and jira_s.jira_user_email and jira_s.jira_api_token:
        async with JiraClient(jira_s) as jira:
            try:
                issue = await jira.get_issue(jira_key, fields=["summary", case_field])
            except JiraAPIError as e:
                print(f"Jira error reading {jira_key}: {e}", file=sys.stderr)
                return 1
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        middleware_case_id = _middleware_case_id_from_issue(issue, case_field)
        summary = str(fields.get("summary") or summary).strip()
    else:
        print("Jira credentials missing — using Stellar case name as summary.", file=sys.stderr)

    if not middleware_case_id:
        middleware_case_id = stellar_case_id
        print(
            f"Jira field {case_field} empty on {jira_key} — using Stellar _id as case_id in email.",
            file=sys.stderr,
        )

    result = await notify_ticket_created(
        jira_key=jira_key,
        case_id=middleware_case_id,
        summary=summary,
        customer_code=customer_code,
        source_id=source_id,
        external_id=stellar_case_id,
        severity=str(case.get("severity") or ""),
        event_name=str(case.get("name") or ""),
        platform="stellar",
        jira_base_url=str(jira_s.jira_base_url) if jira_s.jira_base_url else None,
        stellar_case=case,
        stellar_bundle=bundle,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("sent") else 1


def main() -> int:
    p = argparse.ArgumentParser(
        description="Send SOC notification for an existing Stellar case (does not create Jira ticket)"
    )
    p.add_argument("--case-id", required=True, help="Stellar case _id")
    p.add_argument("--jira-key", help="Override Jira issue key (default: from sync SQLite)")
    args = p.parse_args()
    return asyncio.run(_run(stellar_case_id=args.case_id.strip(), jira_key_override=args.jira_key))


if __name__ == "__main__":
    raise SystemExit(main())
