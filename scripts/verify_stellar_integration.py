#!/usr/bin/env python3
"""Verify Stellar Cyber API + optional Jira AIxSOC project (no issue created)."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import get_jira_settings, get_stellar_settings  # noqa: E402
from app.stellar.client import StellarAPIError, StellarClient  # noqa: E402


async def _stellar_part() -> tuple[bool, str]:
    get_stellar_settings.cache_clear()
    s = get_stellar_settings()
    if not s.stellar_base_url or not s.stellar_api_key:
        return False, "Stellar: set STELLAR_BASE_URL and STELLAR_API_KEY in .env"
    base = str(s.stellar_base_url).rstrip("/")
    lines: list[str] = [f"Stellar checks (host={base})"]

    async with StellarClient(
        base_url=base,
        api_key=s.stellar_api_key,
        timeout_seconds=s.stellar_timeout_seconds,
        verify_tls=s.stellar_tls_verify,
        tenant_id=s.stellar_tenant_id,
        http_max_retries=s.stellar_http_max_retries,
    ) as client:
        # Step 1: poll path (same as automation)
        t0 = time.monotonic()
        try:
            since_ms = int(time.time() * 1000) - s.stellar_sync_lookback_minutes * 60 * 1000
            cases, truncated = await client.fetch_cases_modified_since(
                since_ms,
                page_size=s.stellar_sync_page_size,
                max_pages=1,
            )
            dt = time.monotonic() - t0
            lines.append(
                f"  [poll] fetch_cases_modified_since: OK {dt:.1f}s "
                f"(cases={len(cases)}, truncated={truncated})"
            )
            if not cases:
                lines.append("  [poll] WARN: 0 cases in lookback window (tenant/RBAC/window?)")
            sample_id = str(cases[0].get("_id") or "") if cases else ""
        except StellarAPIError as e:
            dt = time.monotonic() - t0
            lines.append(
                f"  [poll] fetch_cases_modified_since: FAIL {dt:.1f}s "
                f"type={e.error_type} http={e.status_code} {e}"
            )
            # Step 2: tenants (diagnostic when list fails)
            try:
                t1 = time.monotonic()
                await client._request("GET", "tenants")  # noqa: SLF001
                lines.append(f"  [diag] GET /tenants: OK {time.monotonic()-t1:.1f}s")
            except StellarAPIError as te:
                lines.append(f"  [diag] GET /tenants: FAIL {te.error_type} {te}")
            diag_case = (os.environ.get("STELLAR_CASE_ID") or "").strip()
            if diag_case:
                try:
                    t2 = time.monotonic()
                    await client.get_case(diag_case)
                    lines.append(f"  [diag] GET /cases/{{id}}: OK {time.monotonic()-t2:.1f}s")
                except StellarAPIError as ce:
                    lines.append(f"  [diag] GET /cases/{{id}}: FAIL {ce.error_type} {ce}")
            return False, "\n".join(lines) + "\n  → Cases LIST unavailable; integration poll will fail."

        if not sample_id:
            return True, "\n".join(lines) + "\n  Stellar OK (no cases in window; Jira path not exercised)"

        try:
            bundle = await client.fetch_case_bundle(sample_id)
            case = bundle.get("case")
            ok_parts = []
            for part in ("alerts", "observables", "activities", "summary"):
                val = bundle.get(part)
                if isinstance(val, dict) and val.get("error"):
                    ok_parts.append(f"{part}=FAIL")
                else:
                    ok_parts.append(f"{part}=OK")
            lines.append(
                f"  [bundle] case _id={sample_id} ticket_id="
                f"{case.get('ticket_id') if isinstance(case, dict) else '?'} "
                f"{', '.join(ok_parts)}"
            )
        except StellarAPIError as e:
            lines.append(f"  [bundle] FAIL: {e.error_type} {e}")
            return False, "\n".join(lines)

    return True, "\n".join(lines)


def _jira_part() -> tuple[bool, str]:
    get_jira_settings.cache_clear()
    get_stellar_settings.cache_clear()
    j = get_jira_settings()
    st = get_stellar_settings()
    if not j.jira_base_url or not j.jira_user_email or not j.jira_api_token:
        return True, "Jira skipped (JIRA_* not set)"
    base = str(j.jira_base_url).rstrip("/")
    auth = (str(j.jira_user_email), str(j.jira_api_token))
    proj = st.stellar_jira_project_key or "AIXSOC"
    itype = st.stellar_jira_issue_type_id or "10092"
    try:
        r = httpx.get(f"{base}/rest/api/3/project/{proj}", auth=auth, timeout=60.0)
    except httpx.RequestError as e:
        return False, f"Jira project {proj}: request error: {e}"
    if r.status_code != 200:
        return False, f"Jira project {proj}: HTTP {r.status_code}"
    names = [t.get("name") for t in (r.json().get("issueTypes") or []) if t.get("id") == itype]
    itype_name = names[0] if names else "?"
    r2 = httpx.get(
        f"{base}/rest/api/3/issue/createmeta",
        auth=auth,
        params={"projectKeys": proj, "issuetypeIds": itype, "expand": "projects.issuetypes.fields"},
        timeout=60.0,
    )
    if r2.status_code != 200:
        return False, f"Jira createmeta {proj}/{itype}: HTTP {r2.status_code}"
    fields = r2.json()["projects"][0]["issuetypes"][0]["fields"]
    required = [k for k, v in fields.items() if v.get("required")]
    return True, (
        f"Jira OK for Stellar line (project={proj} name={r.json().get('name')!r}, "
        f"issueType id={itype} name={itype_name!r}, required fields={required})"
    )


async def main() -> int:
    s_ok, s_msg = await _stellar_part()
    print(s_msg)
    j_ok, j_msg = _jira_part()
    print(j_msg)
    if s_ok and j_ok:
        print("\nNext: ./Tools/run stellar-sync-dry-run")
        print("      ./Tools/run stellar-cases-repro   # vendor support diagnostics")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
