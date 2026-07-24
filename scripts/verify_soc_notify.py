#!/usr/bin/env python3
"""Send a test SOC notification (email and/or LINE per .env)."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_jira_settings, get_notify_settings, get_stellar_settings  # noqa: E402
from app.jira.client import JiraAPIError, JiraClient  # noqa: E402
from app.notify.stellar_sample_case import sample_stellar_notify_kwargs  # noqa: E402
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


async def _kwargs_from_stellar_case(
    *,
    stellar_case_id: str,
    jira_key_override: str | None,
) -> dict:
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    st = get_stellar_settings()
    if not st.stellar_base_url or not st.stellar_api_key:
        raise ValueError("Set STELLAR_BASE_URL and STELLAR_API_KEY in .env")

    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"
    state = SyncState(ROOT / st.stellar_sync_state_db)
    state.init(legacy_source_id=source_id)

    jira_key = (jira_key_override or state.get_jira_key(source_id, stellar_case_id) or "").strip()
    if not jira_key or jira_key == PENDING_JIRA_KEY:
        raise ValueError(
            f"No Jira key for Stellar case {stellar_case_id!r} in sync DB (pass --jira-key)."
        )

    async with StellarClient(
        base_url=str(st.stellar_base_url).rstrip("/"),
        api_key=st.stellar_api_key,
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
    ) as client:
        bundle = await client.fetch_case_bundle(stellar_case_id)

    case = bundle.get("case")
    if not isinstance(case, dict):
        raise ValueError("Could not parse case from Stellar bundle.")

    customer_code = customer_code_from_case(case, default=st.stellar_default_customer_code)
    case_field = st.stellar_case_id_jira_field or "customfield_10060"
    middleware_case_id = ""
    jira_s = get_jira_settings()
    summary = str(case.get("name") or "").strip()
    if jira_s.jira_base_url and jira_s.jira_user_email and jira_s.jira_api_token:
        async with JiraClient(jira_s) as jira:
            issue = await jira.get_issue(jira_key, fields=["summary", case_field])
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        middleware_case_id = _middleware_case_id_from_issue(issue, case_field)
        summary = str(fields.get("summary") or summary).strip()

    if not middleware_case_id:
        middleware_case_id = stellar_case_id

    return {
        "jira_key": jira_key,
        "case_id": middleware_case_id,
        "summary": summary,
        "customer_code": customer_code,
        "source_id": source_id,
        "external_id": stellar_case_id,
        "severity": str(case.get("severity") or ""),
        "event_name": str(case.get("name") or ""),
        "platform": "stellar",
        "jira_base_url": str(jira_s.jira_base_url) if jira_s.jira_base_url else None,
        "stellar_case": case,
        "stellar_bundle": bundle,
    }


async def _run() -> int:
    p = argparse.ArgumentParser(description="Send a test SOC ticket-created notification email")
    p.add_argument("--jira-key", default=None, help="Sample or live Jira key (default: AIXSOC-TEST)")
    p.add_argument(
        "--case-id",
        help="Use a live Stellar case _id instead of the built-in LOLBIN sample",
    )
    p.add_argument(
        "--platform",
        choices=("cortex", "stellar"),
        default="stellar",
        help="Notification format (default: stellar)",
    )
    args = p.parse_args()

    st = get_notify_settings()
    if not st.soc_notify_enabled and not st.line_notify_enabled:
        print("SOC_NOTIFY_ENABLED and LINE_NOTIFY_ENABLED are both false — enable one in .env", file=sys.stderr)
        return 2
    if st.soc_notify_enabled:
        if not st.is_configured:
            print("Email notify incomplete — set RESEND_API_KEY (or SMTP_HOST) and SOC_NOTIFY_FROM", file=sys.stderr)
            return 2
        if not (st.soc_notify_to or "").strip():
            print("Set SOC_NOTIFY_TO (comma-separated SOC emails)", file=sys.stderr)
            return 2
    if st.line_notify_enabled:
        if not st.line_configured:
            print("LINE notify incomplete — set LINE_CHANNEL_ACCESS_TOKEN", file=sys.stderr)
            return 2
        if not (st.line_notify_to or "").strip():
            print("Set LINE_NOTIFY_TO (comma-separated user/group/room IDs)", file=sys.stderr)
            return 2

    if args.platform == "stellar":
        if args.case_id:
            try:
                kwargs = await _kwargs_from_stellar_case(
                    stellar_case_id=args.case_id.strip(),
                    jira_key_override=args.jira_key,
                )
            except (ValueError, StellarAPIError, JiraAPIError) as e:
                print(str(e), file=sys.stderr)
                return 1
        else:
            kwargs = sample_stellar_notify_kwargs(jira_key=args.jira_key)
    else:
        now_ms = int(time.time() * 1000)
        kwargs = {
            "jira_key": args.jira_key or "AIXSOC-TEST",
            "case_id": "XSOC-JJ-260623-001",
            "summary": "[High][Test Alert][JJ] SOC notify test",
            "customer_code": "JJ",
            "source_id": "test",
            "external_id": "test-incident-001",
            "severity": "high",
            "event_name": "Process requests the deletion of Windows Shadowcopies",
            "platform": "cortex",
            "cortex_incident": {
                "incident_id": "test-incident-001",
                "event_name": "Process requests the deletion of Windows Shadowcopies",
                "severity": "high",
                "creation_time": now_ms,
                "primary_alert_detection_timestamp": now_ms,
                "mitre_tactics_ids_and_names": ["TA0040 - Impact"],
                "hosts": ["desktop-tsbpsh2:agent-001"],
                "users": [r"DESKTOP-TSBPSH2\administrator"],
                "primary_alert_action_pretty": "Prevented (Blocked)",
                "primary_alert_file_path": "",
                "primary_alert_host": "desktop-tsbpsh2",
                "primary_alert_os": "Windows 10",
                "primary_alert_user": "administrator",
            },
        }

    result = await notify_ticket_created(**kwargs)
    print(result)
    return 0 if result.get("sent") else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
