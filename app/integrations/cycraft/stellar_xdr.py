"""POST events to Stellar Cyber XDR Connector webhook."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.cycraft.config import Settings
from app.integrations.cycraft.http_retry import request_with_retry
from app.integrations.cycraft.stellar_ingest import format_ingest_failure, stellar_ingest_succeeded

logger = logging.getLogger(__name__)


class StellarXDRClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._headers = {
            "Authorization": f"Bearer {settings.stellar_xdr_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.connector_http_timeout_seconds),
            verify=settings.connector_tls_verify,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def verify_auth(self) -> dict[str, Any]:
        """Call Stellar authentication webhook path (wizard 'Method and Path')."""
        return await self._post(self._settings.stellar_auth_url(), {})

    async def ingest(self, event: dict[str, Any]) -> dict[str, Any]:
        return await self._post(self._settings.stellar_ingest_url(), event)

    async def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await request_with_retry(
            self._client,
            "POST",
            url,
            headers=self._headers,
            json=body,
        )
        result: dict[str, Any] = {
            "url": url,
            "status_code": response.status_code,
            "body": response.text[:2000],
        }
        if not stellar_ingest_succeeded(response):
            logger.error("Stellar XDR POST rejected: %s", format_ingest_failure(response))
            raise httpx.HTTPStatusError(
                f"Stellar XDR ingest rejected: {format_ingest_failure(response)}",
                request=response.request,
                response=response,
            )
        logger.info("Stellar XDR POST ok status=%s", response.status_code)
        return result
