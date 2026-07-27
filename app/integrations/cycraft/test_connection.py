"""Test CyCraft / Stellar connectivity for a tenant integration."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.cycraft.config import Settings
from app.integrations.cycraft.tenant_config import build_tenant_settings
from app.integrations.cycraft.xcockpit_client import XCockpitClient

logger = logging.getLogger(__name__)


async def test_cycraft_connection(settings: Settings) -> dict[str, Any]:
    """Probe XCockpit and optional Stellar XDR auth webhook."""
    results: dict[str, Any] = {"ok": False, "xcockpit": {}, "stellar_xdr": {}}

    xcockpit_ok = False
    xcockpit_detail: dict[str, Any] = {}
    client = XCockpitClient(settings)
    try:
        created_after = client.default_created_after()
        batch = await client.fetch_alert_items(created_after)
        xcockpit_ok = True
        xcockpit_detail = {
            "ok": True,
            "alert_batch_size": len(batch),
            "since": created_after.isoformat(),
        }
    except Exception as exc:
        logger.warning("XCockpit test failed: %s", exc)
        xcockpit_detail = {"ok": False, "error": str(exc)}
    finally:
        await client.aclose()

    results["xcockpit"] = xcockpit_detail

    stellar_detail: dict[str, Any] = {"ok": False, "skipped": True}
    ingest_path = str(settings.stellar_xdr_ingest_path or "").strip()
    api_key = str(settings.stellar_xdr_api_key or "").strip()
    base_url = str(settings.stellar_base_url or "").strip()
    probe_path = ingest_path or str(settings.stellar_xdr_auth_path or "").strip()
    if probe_path and api_key and base_url:
        stellar_detail = {"ok": False, "skipped": False}
        url = f"{base_url.rstrip('/')}{probe_path}"
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.connector_http_timeout_seconds),
                verify=settings.connector_tls_verify,
            ) as http:
                resp = None
                probe_method = None
                for method in ("OPTIONS", "GET"):
                    try:
                        resp = await http.request(method, url, headers=headers)
                        probe_method = method
                        break
                    except httpx.HTTPError:
                        continue
                if resp is None:
                    raise RuntimeError("webhook probe failed")
            stellar_detail = {
                "ok": resp.status_code < 500,
                "status_code": resp.status_code,
                "skipped": False,
                "probe_method": probe_method,
                "probe_path": probe_path,
            }
        except Exception as exc:
            stellar_detail = {"ok": False, "error": str(exc), "skipped": False}

    results["stellar_xdr"] = stellar_detail
    results["ok"] = bool(xcockpit_ok and (stellar_detail.get("ok") or stellar_detail.get("skipped")))
    return results


async def test_tenant_cycraft(row: dict[str, Any], tenant_source_id: str) -> dict[str, Any]:
    settings = build_tenant_settings(tenant_source_id, row)
    return await test_cycraft_connection(settings)
