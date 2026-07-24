"""Live Stellar Cyber dashboard metrics (Cases API)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import StellarSettings
from app.demo.case_number import CaseNumberIndex, enrich_case_row, load_case_number_index
from app.demo.overview_query import OverviewQuery
from app.demo.case_service import sync_db_path
from app.stellar.case_display_name import stellar_case_display_name
from app.stellar.client import StellarClient
from app.stellar.tenants import get_tenant_by_source_id, load_stellar_tenants

logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERMINAL_STATUSES = frozenset({"resolved", "closed", "cancelled", "done"})
_RECENT_CASES_LIMIT = 50


def _is_open_status(status: str | None) -> bool:
    return str(status or "").strip().lower() not in _TERMINAL_STATUSES


def _resolve_stellar_tenant_id(
    st: StellarSettings,
    tenant_source_id: str | None,
) -> str | None:
    if not tenant_source_id:
        return None
    try:
        tenants = load_stellar_tenants(st, _REPO_ROOT)
    except OSError as e:
        logger.warning("tenant registry load failed: %s", e)
        return None
    tenant = get_tenant_by_source_id(tenants, tenant_source_id)
    if tenant is None:
        return None
    tid = str(tenant.tenant_id or "").strip()
    return tid or None


def _case_ms(case: dict[str, Any], field: str) -> int:
    if field == "created_at":
        return int(case.get("created_at") or 0)
    return int(case.get("modified_at") or 0)


def _row_from_live_case(case: dict[str, Any]) -> dict[str, Any]:
    bundle = {"case": case}
    title = stellar_case_display_name(case, bundle)
    severity = str(case.get("severity") or "").strip() or None
    status = str(case.get("status") or "").strip() or None
    return {
        "stellar_case_id": case.get("_id"),
        "jira_key": None,
        "tenant_source_id": None,
        "tenant_name": case.get("tenant_name"),
        "customer_code": None,
        "title": title,
        "severity": severity,
        "status": status,
        "is_open": _is_open_status(status),
        "created_at_ms": _case_ms(case, "created_at"),
        "modified_at_ms": _case_ms(case, "modified_at"),
    }


async def _fetch_cases(
    client: StellarClient,
    query: OverviewQuery,
    *,
    tenant_id: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    if query.since_ms is None:
        return await client.list_all_cases(
            page_size=200,
            max_pages=15,
            sort="modified_at",
            order="desc",
            tenant_id=tenant_id,
        )
    if query.scope_field == "modified_at":
        return await client.fetch_cases_modified_since(
            query.since_ms,
            page_size=100,
            max_pages=15,
            tenant_id=tenant_id,
        )
    return await client.fetch_cases_created_since(
        query.since_ms,
        page_size=100,
        max_pages=15,
        tenant_id=tenant_id,
    )


def _aggregate(
    cases: list[dict[str, Any]],
    query: OverviewQuery,
    *,
    number_index: CaseNumberIndex | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    total = 0
    open_count = 0
    critical_high = 0
    new_in_window = 0
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_tenant: dict[str, int] = {}
    recent: list[dict[str, Any]] = []

    for case in cases:
        row = enrich_case_row(_row_from_live_case(case), number_index)
        total += 1
        if row.get("is_open"):
            open_count += 1
        sev = str(row.get("severity") or "Unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if sev in {"Critical", "High"} and row.get("is_open"):
            critical_high += 1
        status = str(row.get("status") or "Unknown")
        by_status[status] = by_status.get(status, 0) + 1
        tenant_key = str(row.get("tenant_name") or "unknown")
        by_tenant[tenant_key] = by_tenant.get(tenant_key, 0) + 1
        basis_ms = _case_ms(case, query.new_basis_field)
        if query.since_ms is None:
            new_in_window += 1
        elif basis_ms >= query.since_ms:
            new_in_window += 1
        if len(recent) < _RECENT_CASES_LIMIT:
            recent.append(row)

    return {
        "summary": {
            "total_cases": total,
            "open_cases": open_count,
            "critical_high_open": critical_high,
            "new_in_window": new_in_window,
        },
        "by_severity": by_severity,
        "by_status": by_status,
        "by_tenant": by_tenant,
        "recent_cases": recent,
        "meta": {
            "source": "stellar_live",
            "window": query.window,
            "scope": query.scope,
            "new_basis": query.new_basis,
            "since": query.since_iso,
            "as_of": now.isoformat(),
        },
    }


async def build_live_overview(
    st: StellarSettings,
    query: OverviewQuery,
    *,
    tenant_source_id: str | None = None,
) -> dict[str, Any]:
    base = str(st.stellar_base_url or "").strip()
    api_key = str(st.stellar_api_key or "").strip()
    if not base or not api_key:
        raise RuntimeError("Stellar API not configured")

    tenant_id = _resolve_stellar_tenant_id(st, tenant_source_id)
    async with StellarClient(base_url=base, api_key=api_key) as client:
        cases, truncated = await _fetch_cases(client, query, tenant_id=tenant_id)

    if tenant_source_id and not tenant_id:
        needle = tenant_source_id.strip().lower()
        filtered = [
            c
            for c in cases
            if needle in str(c.get("tenant_name") or "").lower()
            or needle in str(c.get("cust_id") or "").lower()
        ]
        cases = filtered

    source_id = str(st.stellar_poll_source_id or "stellar").strip() or "stellar"
    number_index = load_case_number_index(sync_db_path(st), source_id)
    payload = _aggregate(cases, query, number_index=number_index)
    payload["meta"]["truncated"] = truncated
    if tenant_source_id:
        payload["meta"]["tenant_source_id"] = tenant_source_id
    return payload
