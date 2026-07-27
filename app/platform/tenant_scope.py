"""Strict tenant boundary for settings and admin APIs."""

from __future__ import annotations

from fastapi import HTTPException

from app.platform.deps import CurrentUser


def settings_tenant_scope(current: CurrentUser) -> str | None:
    """``None`` = platform scope (all tenants); else fixed tenant for tenant roles."""
    if current.is_platform_scope():
        return None
    if current.role == "tenant_admin":
        tid = current.tenant_source_id
        if not tid:
            raise HTTPException(status_code=403, detail="Tenant admin missing tenant_source_id")
        return tid
    raise HTTPException(status_code=403, detail="Insufficient permissions")


def can_manage_tenant_settings(current: CurrentUser) -> bool:
    return current.role in {"platform_admin", "tenant_admin"}


def assert_tenant_settings_access(
    current: CurrentUser,
    tenant_source_id: str,
    *,
    scope: str | None = None,
) -> None:
    """Ensure the user may read/write settings for ``tenant_source_id`` only."""
    allowed = scope if scope is not None else settings_tenant_scope(current)
    tid = str(tenant_source_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_source_id required")
    if allowed is not None and tid != allowed:
        raise HTTPException(status_code=403, detail="Tenant settings access denied")
