"""Per-tenant CyCraft integration config (DB + env secrets)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.integrations.cycraft.config import Settings, load_settings
from app.platform.tenant_secrets import (
    read_cycraft_secret,
    tenant_secret_configured,
)


def _parse_config_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def cycraft_config_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    cfg = _parse_config_json(row.get("config_json"))
    cycraft = cfg.get("cycraft")
    return dict(cycraft) if isinstance(cycraft, dict) else {}


def tenant_state_db_path(tenant_source_id: str, base: Path | None = None) -> Path:
    root = base or Path("data/cycraft_state")
    return root / f"{tenant_source_id}.sqlite"


def tenant_cycraft_configured(tenant_source_id: str, row: dict[str, Any] | None) -> bool:
    if not row or not row.get("cycraft_enabled"):
        return False
    cfg = cycraft_config_from_row(row)
    customer = str(row.get("xcockpit_customer_key") or "").strip()
    ingest = str(cfg.get("stellar_xdr_ingest_path") or "").strip()
    return (
        customer
        and ingest
        and tenant_secret_configured(tenant_source_id, "XCOCKPIT_API_KEY", cfg)
        and tenant_secret_configured(tenant_source_id, "STELLAR_XDR_API_KEY", cfg)
    )


def build_tenant_settings(tenant_source_id: str, row: dict[str, Any]) -> Settings:
    """Build runtime Settings for one tenant (isolated credentials + paths)."""
    base = load_settings()
    cfg = cycraft_config_from_row(row)
    tid = str(tenant_source_id).strip()
    ingest = str(cfg.get("stellar_xdr_ingest_path") or "").strip()
    auth = str(cfg.get("stellar_xdr_auth_path") or "").strip()
    xcockpit_base = str(cfg.get("xcockpit_base_url") or base.xcockpit_base_url or "").strip()
    customer = str(row.get("xcockpit_customer_key") or "").strip()
    stellar_tid = str(cfg.get("stellar_tenant_id") or base.stellar_tenant_id or "").strip()

    return Settings(
        stellar_base_url=str(base.stellar_base_url or "").strip(),
        stellar_xdr_api_key=read_cycraft_secret(tid, "STELLAR_XDR_API_KEY", cfg),
        stellar_xdr_ingest_path=ingest,
        stellar_xdr_auth_path=auth,
        stellar_xdr_vendor=base.stellar_xdr_vendor,
        stellar_xdr_source=base.stellar_xdr_source,
        stellar_xdr_timestamp_path=base.stellar_xdr_timestamp_path,
        stellar_xdr_timestamp_format=base.stellar_xdr_timestamp_format,
        xcockpit_base_url=xcockpit_base,
        xcockpit_api_key=read_cycraft_secret(tid, "XCOCKPIT_API_KEY", cfg),
        xcockpit_customer_key=customer,
        xcockpit_poll_mode=cfg.get("xcockpit_poll_mode") or base.xcockpit_poll_mode,
        xcockpit_poll_interval_seconds=base.xcockpit_poll_interval_seconds,
        xcockpit_poll_lookback_minutes=base.xcockpit_poll_lookback_minutes,
        xcockpit_incident_page_size=base.xcockpit_incident_page_size,
        xcockpit_include_cycraft_c=bool(
            cfg.get("xcockpit_include_cycraft_c", base.xcockpit_include_cycraft_c)
        ),
        incident_case_sync_enabled=bool(
            cfg.get("incident_case_sync_enabled", base.incident_case_sync_enabled)
        ),
        incident_maltrace_ingest=bool(
            cfg.get("incident_maltrace_ingest", base.incident_maltrace_ingest)
        ),
        stellar_cases_api_key=read_cycraft_secret(tid, "STELLAR_CASES_API_KEY", cfg)
        or str(base.stellar_cases_api_key or "").strip(),
        stellar_tenant_id=stellar_tid,
        connector_state_db=tenant_state_db_path(tid),
        cycraft_connector_enabled=base.cycraft_connector_enabled,
        connector_tls_verify=base.connector_tls_verify,
        connector_http_timeout_seconds=base.connector_http_timeout_seconds,
    )


def public_cycraft_settings(
    tenant_source_id: str,
    row: dict[str, Any] | None,
    *,
    master_enabled: bool,
) -> dict[str, Any]:
    cfg = cycraft_config_from_row(row)
    enabled = bool(row and row.get("cycraft_enabled"))
    env_ok = tenant_cycraft_configured(tenant_source_id, row)
    return {
        "connector_type": "cycraft",
        "enabled": enabled,
        "xcockpit_customer_key": row.get("xcockpit_customer_key") if row else None,
        "stellar_xdr_ingest_path": cfg.get("stellar_xdr_ingest_path"),
        "stellar_xdr_auth_path": cfg.get("stellar_xdr_auth_path"),
        "xcockpit_base_url": cfg.get("xcockpit_base_url"),
        "secrets": {
            "xcockpit_api_key": tenant_secret_configured(
                tenant_source_id, "XCOCKPIT_API_KEY", cfg
            ),
            "stellar_xdr_api_key": tenant_secret_configured(
                tenant_source_id, "STELLAR_XDR_API_KEY", cfg
            ),
            "stellar_cases_api_key": tenant_secret_configured(
                tenant_source_id, "STELLAR_CASES_API_KEY", cfg
            ),
        },
        "runtime_active": master_enabled and env_ok,
        "config_complete": env_ok,
    }
