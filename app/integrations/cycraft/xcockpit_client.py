"""XCockpit API client (CyCraft EDR) — v2.1.0."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from app.integrations.cycraft.config import Settings
from app.integrations.cycraft.http_retry import request_with_retry

logger = logging.getLogger(__name__)

PollMode = Literal["alerts", "incidents", "both"]


class XCockpitClient:
    """https://xcockpit.cycraft.ai — Authorization: Token <API_KEY>."""

    def __init__(self, settings: Settings) -> None:
        if not settings.xcockpit_base_url:
            raise ValueError("Set XCOCKPIT_BASE_URL")
        if not settings.xcockpit_api_key:
            raise ValueError("Set XCOCKPIT_API_KEY")
        if not settings.xcockpit_customer_key:
            raise ValueError("Set XCOCKPIT_CUSTOMER_KEY (Customer UUID from XCockpit Management)")
        self._settings = settings
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Token {settings.xcockpit_api_key}",
        }
        self._api_root = (
            f"{settings.xcockpit_base_url.rstrip('/')}/_api/{settings.xcockpit_customer_key}"
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.connector_http_timeout_seconds),
            verify=settings.connector_tls_verify,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_alerts(self, created_after: datetime) -> list[dict[str, Any]]:
        created = _format_xcockpit_datetime(created_after)
        payload = await self._get("/alert", params={"created": created})
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def get_edr_alert(self, alert_id: str) -> dict[str, Any]:
        payload = await self._get(f"/edr_alert/{alert_id}/json")
        if not isinstance(payload, dict):
            raise ValueError(f"EDR alert {alert_id}: expected JSON object")
        return payload

    async def get_cyber_situation_report(self, report_id: str) -> dict[str, Any]:
        payload = await self._get(f"/cyber_situation_report/{report_id}/json")
        if not isinstance(payload, dict):
            raise ValueError(f"Cyber situation report {report_id}: expected JSON object")
        return payload

    async def list_incidents(
        self,
        created_after: datetime,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "created_after": _format_xcockpit_datetime(created_after),
            "offset": str(offset),
            "limit": str(limit or self._settings.xcockpit_incident_page_size),
        }
        payload = await self._get("/incident", params=params)
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def fetch_alert_items(self, created_after: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        alert_refs = await self.list_alerts(created_after)
        edr_refs = [a for a in alert_refs if a.get("type") == "CYCRAFT_E"]
        csr_refs = [a for a in alert_refs if a.get("type") == "CYCRAFT_C"]
        logger.info(
            "XCockpit alert list: %s total, %s EDR, %s CSR",
            len(alert_refs),
            len(edr_refs),
            len(csr_refs),
        )
        for ref in edr_refs:
            alert_id = str(ref.get("id", "")).strip()
            if not alert_id:
                continue
            try:
                report = await self.get_edr_alert(alert_id)
                report["_xcockpit_alert_ref"] = ref
                events.append({"kind": "edr_alert", "payload": report})
            except Exception:
                logger.exception("Failed to fetch EDR alert id=%s", alert_id)

        if self._settings.xcockpit_include_cycraft_c:
            for ref in csr_refs:
                report_id = str(ref.get("id", "")).strip()
                if not report_id:
                    continue
                try:
                    report = await self.get_cyber_situation_report(report_id)
                    report["_xcockpit_alert_ref"] = ref
                    events.append({"kind": "csr_report", "payload": report})
                except Exception:
                    logger.exception("Failed to fetch CSR report id=%s", report_id)
        elif csr_refs:
            logger.info("Skipping %s CYCRAFT_C alert(s); XCOCKPIT_INCLUDE_CYCRAFT_C=false", len(csr_refs))

        return events

    async def fetch_incident_items(self, created_after: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        offset = 0
        page_size = self._settings.xcockpit_incident_page_size
        while True:
            incidents = await self.list_incidents(
                created_after, offset=offset, limit=page_size
            )
            if not incidents:
                break
            for incident in incidents:
                events.append({"kind": "incident", "payload": incident})
            if len(incidents) < page_size:
                break
            offset += page_size
        return events

    async def fetch_poll_batch(
        self,
        created_after: datetime,
        *,
        mode: PollMode | None = None,
    ) -> list[dict[str, Any]]:
        """Backfill helper — combines alert/incident streams for one ``since`` timestamp."""
        mode = mode or self._settings.xcockpit_poll_mode
        events: list[dict[str, Any]] = []
        if mode in ("alerts", "both"):
            events.extend(await self.fetch_alert_items(created_after))
        if mode in ("incidents", "both"):
            events.extend(await self.fetch_incident_items(created_after))
        return events

    def default_created_after(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(
            minutes=self._settings.xcockpit_poll_lookback_minutes
        )

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._api_root}{path}"
        response = await request_with_retry(
            self._client,
            "GET",
            url,
            headers=self._headers,
            params=params,
        )
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"XCockpit API HTTP {response.status_code}: {response.text[:500]}",
                request=response.request,
                response=response,
            )
        return response.json()


def _format_xcockpit_datetime(dt: datetime) -> str:
    """ISO 8601 with offset, e.g. 2023-06-30T01:01:01+08:00."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")
