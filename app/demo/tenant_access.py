"""Tenant scope helpers for demo API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import StellarSettings
from app.platform.deps import CurrentUser
from app.stellar.tenant_model import StellarTenant
from app.stellar.tenants import get_tenant_by_source_id, load_stellar_tenants

_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_registry_tenant(st: StellarSettings, tenant_source_id: str) -> StellarTenant | None:
    tenants = load_stellar_tenants(st, _REPO_ROOT)
    return get_tenant_by_source_id(tenants, tenant_source_id)


def stellar_api_tenant_id(st: StellarSettings, tenant_source_id: str | None) -> str | None:
    """Stellar Cases API tenant_id query param (skip unresolved env placeholders)."""
    if not tenant_source_id:
        return None
    tenant = get_registry_tenant(st, tenant_source_id)
    if tenant is None:
        return None
    tid = str(tenant.tenant_id or "").strip()
    if not tid or "${" in tid:
        return None
    return tid


def live_case_matches_tenant(case: dict[str, Any], tenant: StellarTenant) -> bool:
    """Exact tenant match for Stellar live case payloads (no substring matching)."""
    cust_id = str(case.get("cust_id") or "").strip()
    case_tid = str(case.get("tenant_id") or "").strip() or cust_id
    case_name = str(case.get("tenant_name") or "").strip().lower()

    reg_tid = str(tenant.tenant_id or "").strip()
    if reg_tid and case_tid == reg_tid:
        return True

    cc = str(tenant.customer_code or "").strip().upper()
    if cc and cust_id.upper() == cc:
        return True

    tn = str(tenant.tenant_name or "").strip().lower()
    if tn and case_name == tn:
        return True

    return False


def filter_live_cases_for_tenant(
    st: StellarSettings,
    tenant_source_id: str,
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tenant = get_registry_tenant(st, tenant_source_id)
    if tenant is None:
        return []
    return [c for c in cases if live_case_matches_tenant(c, tenant)]


def effective_tenant_source_id(
    current: CurrentUser,
    tenant_param: str | None = None,
) -> str | None:
    """Resolve tenant filter for data APIs.

    Platform scope: ``tenant_param`` selects tenant; empty = all tenants.
    Tenant scope: always own ``tenant_source_id``; mismatch → 403.
    """
    param = str(tenant_param or "").strip() or None
    if current.is_platform_scope():
        return param
    own = current.tenant_source_id
    if not own:
        raise HTTPException(status_code=403, detail="Tenant account missing tenant_source_id")
    if param and param != own:
        raise HTTPException(status_code=403, detail="Tenant access denied")
    return own


def list_visible_tenants(st: StellarSettings, current: CurrentUser) -> list[dict[str, Any]]:
    tenants = load_stellar_tenants(st, _REPO_ROOT)
    if current.is_platform_scope():
        visible = [t for t in tenants if t.enabled]
    else:
        own = current.tenant_source_id
        if not own:
            return []
        t = get_tenant_by_source_id(tenants, own)
        visible = [t] if t is not None and t.enabled else []
    return [
        {
            "source_id": t.source_id,
            "tenant_name": t.tenant_name,
            "customer_code": t.customer_code,
            "report_title": t.report_title or t.tenant_name or t.customer_code,
            "sync_enabled": t.sync_enabled,
        }
        for t in visible
    ]


def can_manage_users(current: CurrentUser) -> bool:
    return current.role in {"platform_admin", "tenant_admin"}


def user_admin_tenant_scope(current: CurrentUser) -> str | None:
    """``None`` = platform admin (all tenants); else fixed tenant for tenant_admin."""
    if current.role == "platform_admin":
        return None
    if current.role == "tenant_admin":
        tid = current.tenant_source_id
        if not tid:
            raise HTTPException(status_code=403, detail="Tenant admin missing tenant_source_id")
        return tid
    raise HTTPException(status_code=403, detail="Insufficient permissions")


def assert_link_in_tenant_scope(
    link: dict[str, Any],
    tenant_source_id: str | None,
) -> None:
    """Raise PermissionError when a scoped session cannot access the incident link."""
    if not tenant_source_id:
        return
    link_tid = str(link.get("tenant_source_id") or "").strip()
    if link_tid != tenant_source_id:
        raise PermissionError("tenant access denied")


def filter_rows_by_tenant(
    rows: list[dict[str, Any]],
    tenant_source_id: str | None,
) -> list[dict[str, Any]]:
    if not tenant_source_id:
        return rows
    tid = tenant_source_id.strip()
    return [
        row
        for row in rows
        if str(row.get("tenant_source_id") or "").strip() == tid
    ]


def assert_user_in_admin_scope(
    current: CurrentUser,
    target: dict[str, Any],
    *,
    admin_tenant: str | None,
) -> None:
    if admin_tenant is None:
        return
    target_tid = str(target.get("tenant_source_id") or "").strip()
    target_role = str(target.get("role") or "")
    if target_role in {"platform_admin", "soc_analyst", "soc_viewer"}:
        raise HTTPException(status_code=403, detail="Cannot manage platform users")
    if target_tid != admin_tenant:
        raise HTTPException(status_code=403, detail="Cannot manage users outside your tenant")
