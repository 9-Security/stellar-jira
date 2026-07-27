"""Tenant-scoped settings API (integrations and future tenant config)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import StellarSettings, get_stellar_settings
from app.demo.tenant_access import list_visible_tenants
from app.integrations.cycraft.config import load_settings
from app.integrations.cycraft.tenant_config import (
    build_tenant_settings,
    public_cycraft_settings,
)
from app.integrations.cycraft.test_connection import test_cycraft_connection
from app.platform.deps import (
    CurrentUser,
    audit_request_ip,
    get_platform_store,
    require_full_session,
)
from app.platform.store import PlatformStore
from app.platform.tenant_scope import (
    assert_tenant_settings_access,
    can_manage_tenant_settings,
    settings_tenant_scope,
)
from app.platform.tenant_secrets import encrypt_cycraft_secrets

router = APIRouter(prefix="/v1/settings", tags=["settings"])


class CycraftConfigPatch(BaseModel):
    enabled: bool | None = None
    xcockpit_customer_key: str | None = Field(default=None, max_length=128)
    stellar_xdr_ingest_path: str | None = Field(default=None, max_length=512)
    stellar_xdr_auth_path: str | None = Field(default=None, max_length=512)
    xcockpit_base_url: str | None = Field(default=None, max_length=256)
    stellar_tenant_id: str | None = Field(default=None, max_length=128)
    xcockpit_api_key: str | None = Field(default=None, max_length=512)
    stellar_xdr_api_key: str | None = Field(default=None, max_length=512)
    stellar_cases_api_key: str | None = Field(default=None, max_length=512)


class CycraftTestBody(BaseModel):
    xcockpit_customer_key: str | None = Field(default=None, max_length=128)
    stellar_xdr_ingest_path: str | None = Field(default=None, max_length=512)
    stellar_xdr_auth_path: str | None = Field(default=None, max_length=512)
    xcockpit_base_url: str | None = Field(default=None, max_length=256)
    xcockpit_api_key: str | None = Field(default=None, max_length=512)
    stellar_xdr_api_key: str | None = Field(default=None, max_length=512)
    stellar_cases_api_key: str | None = Field(default=None, max_length=512)


async def require_settings_manager(
    current: Annotated[CurrentUser, Depends(require_full_session)],
) -> CurrentUser:
    if not can_manage_tenant_settings(current):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return current


def _integration_payload(
    tenant: dict[str, Any],
    row: dict[str, Any] | None,
    *,
    master_enabled: bool,
) -> dict[str, Any]:
    tid = str(tenant["source_id"])
    cycraft = public_cycraft_settings(tid, row, master_enabled=master_enabled)
    connectors: list[dict[str, Any]] = []
    if cycraft.get("enabled"):
        connectors.append(cycraft)
    return {
        "tenant_source_id": tid,
        "tenant_name": tenant.get("tenant_name"),
        "report_title": tenant.get("report_title"),
        "customer_code": tenant.get("customer_code"),
        "connectors": connectors,
        "integrations": {
            "cycraft": cycraft,
        },
    }


def _merge_rows(
    st: StellarSettings,
    current: CurrentUser,
    store: PlatformStore,
) -> list[dict[str, Any]]:
    tenants = list_visible_tenants(st, current)
    by_id = {row["tenant_source_id"]: row for row in store.list_tenant_integrations()}
    master = bool(load_settings().cycraft_connector_enabled)
    return [
        _integration_payload(t, by_id.get(str(t["source_id"])), master_enabled=master)
        for t in tenants
    ]


def _secret_patch(body: CycraftConfigPatch | CycraftTestBody) -> dict[str, str]:
    out: dict[str, str] = {}
    if body.xcockpit_api_key:
        out["xcockpit_api_key"] = body.xcockpit_api_key.strip()
    if body.stellar_xdr_api_key:
        out["stellar_xdr_api_key"] = body.stellar_xdr_api_key.strip()
    if body.stellar_cases_api_key:
        out["stellar_cases_api_key"] = body.stellar_cases_api_key.strip()
    return out


@router.get("/integrations")
def list_tenant_integrations(
    current: Annotated[CurrentUser, Depends(require_settings_manager)],
    store: PlatformStore = Depends(get_platform_store),
    st: StellarSettings = Depends(get_stellar_settings),
) -> dict[str, Any]:
    master = load_settings()
    rows = _merge_rows(st, current, store)
    all_connectors = []
    for row in rows:
        for conn in row.get("connectors") or []:
            all_connectors.append(
                {
                    **conn,
                    "tenant_source_id": row["tenant_source_id"],
                    "tenant_name": row.get("tenant_name"),
                    "report_title": row.get("report_title"),
                    "customer_code": row.get("customer_code"),
                }
            )
    return {
        "data": rows,
        "connectors": all_connectors,
        "meta": {
            "scope": "tenant",
            "cycraft_service_enabled": bool(master.cycraft_connector_enabled),
            "connector_types": [
                {"id": "cycraft", "label": "CyCraft Connector"},
            ],
        },
    }


@router.patch("/integrations/{tenant_source_id}")
def patch_tenant_integrations(
    tenant_source_id: str,
    body: CycraftConfigPatch,
    request: Request,
    current: Annotated[CurrentUser, Depends(require_settings_manager)],
    store: PlatformStore = Depends(get_platform_store),
    st: StellarSettings = Depends(get_stellar_settings),
) -> dict[str, Any]:
    tid = str(tenant_source_id or "").strip()
    assert_tenant_settings_access(current, tid, scope=settings_tenant_scope(current))

    visible = {t["source_id"] for t in list_visible_tenants(st, current)}
    if tid not in visible:
        raise HTTPException(status_code=404, detail="Tenant not found")

    existing = store.get_tenant_integration(tid)
    secret_fields = _secret_patch(body)
    if (
        body.enabled is None
        and body.xcockpit_customer_key is None
        and body.stellar_xdr_ingest_path is None
        and body.stellar_xdr_auth_path is None
        and body.xcockpit_base_url is None
        and body.stellar_tenant_id is None
        and not secret_fields
    ):
        raise HTTPException(status_code=400, detail="No fields to update")

    enabled = (
        body.enabled
        if body.enabled is not None
        else bool(existing and existing.get("cycraft_enabled"))
        if existing
        else True
    )
    config_patch: dict[str, Any] = {}
    if body.stellar_xdr_ingest_path is not None:
        config_patch["stellar_xdr_ingest_path"] = body.stellar_xdr_ingest_path.strip() or None
    if body.stellar_xdr_auth_path is not None:
        config_patch["stellar_xdr_auth_path"] = body.stellar_xdr_auth_path.strip() or None
    if body.xcockpit_base_url is not None:
        config_patch["xcockpit_base_url"] = body.xcockpit_base_url.strip() or None
    if body.stellar_tenant_id is not None:
        config_patch["stellar_tenant_id"] = body.stellar_tenant_id.strip() or None
    if secret_fields:
        config_patch["secrets_enc"] = encrypt_cycraft_secrets(secret_fields)

    row = store.set_cycraft_enabled(
        tid,
        enabled=enabled,
        updated_by_user_id=current.id,
        xcockpit_customer_key=body.xcockpit_customer_key,
        cycraft_config=config_patch if config_patch else None,
    )
    store.record_audit(
        user_id=current.id,
        action="tenant_settings_updated",
        resource_type="tenant_integration",
        resource_id=tid,
        tenant_source_id=tid,
        ip_address=audit_request_ip(request),
        detail={
            "cycraft_enabled": row.get("cycraft_enabled"),
            "xcockpit_customer_key": row.get("xcockpit_customer_key"),
            "cycraft_config_keys": [k for k in config_patch if k != "secrets_enc"],
            "secrets_updated": bool(secret_fields),
        },
    )
    tenant_meta = next(
        (t for t in list_visible_tenants(st, current) if t["source_id"] == tid),
        None,
    )
    if tenant_meta is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    master = bool(load_settings().cycraft_connector_enabled)
    return {
        "data": _integration_payload(tenant_meta, row, master_enabled=master),
    }


@router.post("/integrations/{tenant_source_id}/cycraft/test")
async def test_cycraft_integration(
    tenant_source_id: str,
    body: CycraftTestBody | None = None,
    current: Annotated[CurrentUser, Depends(require_settings_manager)] = None,
    store: PlatformStore = Depends(get_platform_store),
    st: StellarSettings = Depends(get_stellar_settings),
) -> dict[str, Any]:
    tid = str(tenant_source_id or "").strip()
    assert_tenant_settings_access(current, tid, scope=settings_tenant_scope(current))

    visible = {t["source_id"] for t in list_visible_tenants(st, current)}
    if tid not in visible:
        raise HTTPException(status_code=404, detail="Tenant not found")

    row = store.get_tenant_integration(tid) or {
        "tenant_source_id": tid,
        "cycraft_enabled": False,
        "xcockpit_customer_key": None,
        "config_json": None,
    }
    settings = build_tenant_settings(tid, row)
    if body is not None:
        updates: dict[str, Any] = {}
        if body.xcockpit_customer_key and body.xcockpit_customer_key.strip():
            updates["xcockpit_customer_key"] = body.xcockpit_customer_key.strip()
        if body.stellar_xdr_ingest_path and body.stellar_xdr_ingest_path.strip():
            updates["stellar_xdr_ingest_path"] = body.stellar_xdr_ingest_path.strip()
        if body.stellar_xdr_auth_path and body.stellar_xdr_auth_path.strip():
            updates["stellar_xdr_auth_path"] = body.stellar_xdr_auth_path.strip()
        if body.xcockpit_base_url and body.xcockpit_base_url.strip():
            updates["xcockpit_base_url"] = body.xcockpit_base_url.strip()
        if body.xcockpit_api_key and body.xcockpit_api_key.strip():
            updates["xcockpit_api_key"] = body.xcockpit_api_key.strip()
        if body.stellar_xdr_api_key and body.stellar_xdr_api_key.strip():
            updates["stellar_xdr_api_key"] = body.stellar_xdr_api_key.strip()
        if body.stellar_cases_api_key and body.stellar_cases_api_key.strip():
            updates["stellar_cases_api_key"] = body.stellar_cases_api_key.strip()
        if updates:
            settings = settings.model_copy(update=updates)

    result = await test_cycraft_connection(settings)
    return {"data": result}
