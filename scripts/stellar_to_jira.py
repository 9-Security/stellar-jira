#!/usr/bin/env python3
"""Stellar Cyber case → Jira AIxSOC issue (default: dry-run)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_jira_settings, get_stellar_settings  # noqa: E402
from app.jira.client import JiraAPIError, JiraClient  # noqa: E402
from app.stellar.client import StellarAPIError, StellarClient  # noqa: E402
from app.stellar.jira_draft import build_jira_issue_fields  # noqa: E402
from app.stellar.severity_filter import case_severity_allowed, normalize_stellar_severity  # noqa: E402
from app.stellar.tenant_code import customer_code_from_case  # noqa: E402
from app.sync.case_id import commit_case_id, peek_next_case_id  # noqa: E402
from app.sync.state import SyncState  # noqa: E402


async def _run(*, case_id: str | None, dry_run: bool) -> int:
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    st = get_stellar_settings()
    if not st.stellar_base_url or not st.stellar_api_key:
        print("Set STELLAR_BASE_URL and STELLAR_API_KEY in .env", file=sys.stderr)
        return 2

    base = str(st.stellar_base_url).rstrip("/")
    proj = st.stellar_jira_project_key or "AIXSOC"
    itype_id = st.stellar_jira_issue_type_id or "10092"

    async with StellarClient(
        base_url=base,
        api_key=st.stellar_api_key,
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=st.stellar_tenant_id,
    ) as client:
        try:
            if case_id:
                bundle = await client.fetch_case_bundle(case_id)
            else:
                listed = await client.list_cases(limit=1)
                cases = StellarClient.extract_cases_list(listed)
                if not cases:
                    print("No Stellar cases returned.", file=sys.stderr)
                    return 1
                case_id = str(cases[0].get("_id") or "")
                bundle = await client.fetch_case_bundle(case_id)
        except StellarAPIError as e:
            print(f"Stellar error: {e}", file=sys.stderr)
            return 1

    case = bundle.get("case")
    if not isinstance(case, dict):
        print("Could not parse case from Stellar response.", file=sys.stderr)
        return 1

    try:
        customer_code = customer_code_from_case(
            case, default=st.stellar_default_customer_code
        )
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2

    allowed = st.allowed_sync_severities()
    if not case_severity_allowed(case, allowed):
        label = normalize_stellar_severity(case.get("severity")) or "?"
        allowed_txt = ", ".join(sorted(allowed or ()))
        print(
            f"Severity {label!r} not in STELLAR_SYNC_ALLOWED_SEVERITIES ({allowed_txt}) — skip.",
            file=sys.stderr,
        )
        return 2

    state_path = ROOT / st.stellar_sync_state_db
    state = SyncState(state_path)
    state.init(legacy_source_id="stellar")

    middleware_case_id = peek_next_case_id(
        state,
        prefix=st.stellar_case_id_prefix,
        customer_code=customer_code,
        timezone_name=st.stellar_case_id_timezone,
    )

    sev_field = st.stellar_jira_severity_field or "customfield_10057"
    status_field = st.stellar_jira_status_field or "customfield_10061"
    alert_field = st.stellar_jira_alert_name_field
    res_tag_field = (st.stellar_jira_resolution_tag_field or "").strip() or None
    case_field = st.stellar_case_id_jira_field or "customfield_10060"
    fields = build_jira_issue_fields(
        project_key=proj,
        issue_type_id=itype_id,
        severity_field_id=sev_field,
        status_field_id=status_field,
        alert_name_field_id=alert_field,
        resolution_tag_field_id=res_tag_field,
        case_id_jira_field=case_field,
        summary_template=st.stellar_summary_template,
        customer_code=customer_code,
        middleware_case_id=middleware_case_id,
        case=case,
        bundle=bundle,
    )
    print(f"Stellar case _id={case_id} ticket_id={case.get('ticket_id')}")
    print(f"客戶代號 (tenant_name): {customer_code}")
    print(f"案件編號: {middleware_case_id}")
    print(f"Jira target: project={proj} issuetype.id={itype_id}")
    print(f"Summary: {fields.get('summary')}")
    print(f"嚴重程度 ({sev_field}): {(fields.get(sev_field) or {}).get('value')}")
    st_opt = (fields.get(status_field) or {}).get("value")
    print(f"事件狀態 ({status_field}): {st_opt if st_opt else '(skipped — no matching Stellar status)'}")
    print(f"告警名稱 ({alert_field}): set from Stellar case name")
    if res_tag_field:
        rt = fields.get(res_tag_field)
        print(
            f"resolution tag ({res_tag_field}): "
            f"{(rt or {}).get('value') or '(empty — no matching Stellar tags on case)'}"
        )

    if dry_run:
        print("\n--- dry-run: issue fields (truncated description) ---")
        preview = dict(fields)
        desc = preview.get("description")
        if isinstance(desc, dict):
            preview["description"] = {"type": "doc", "version": 1, "content": ["…"]}
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        print("\nTo create: add --create")
        return 0

    j = get_jira_settings()
    if not j.jira_base_url or not j.jira_user_email or not j.jira_api_token:
        print("JIRA_* required for --create", file=sys.stderr)
        return 2
    jira = JiraClient(j)
    try:
        out = await jira.create_issue_resilient(fields)
    except JiraAPIError as e:
        print(f"Jira create failed: {e}", file=sys.stderr)
        if e.body is not None:
            print(json.dumps(e.body, indent=2, default=str)[:4000], file=sys.stderr)
        return 1
    commit_case_id(
        state,
        prefix=st.stellar_case_id_prefix,
        customer_code=customer_code,
        timezone_name=st.stellar_case_id_timezone,
    )
    key = out.get("key")
    print(f"Created Jira issue: {key}")
    print(f"Link: {j.jira_base_url}/browse/{key}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Stellar case → Jira AIxSOC")
    p.add_argument("--case-id", help="Stellar case _id (default: latest case)")
    p.add_argument(
        "--create",
        action="store_true",
        help="Actually create Jira issue (default is dry-run only)",
    )
    args = p.parse_args()
    return asyncio.run(_run(case_id=args.case_id, dry_run=not args.create))


if __name__ == "__main__":
    raise SystemExit(main())
