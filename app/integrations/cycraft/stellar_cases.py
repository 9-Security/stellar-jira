"""Minimal Stellar Cyber Cases API client (update / comment only on 6.5.x)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.cycraft.config import Settings

logger = logging.getLogger(__name__)


class StellarCasesClient:
    """Platform Cases API — separate from XDR webhook ingest key."""

    def __init__(self, settings: Settings) -> None:
        if not settings.stellar_cases_api_key:
            raise ValueError("Set STELLAR_CASES_API_KEY for Cases API")
        self._base = settings.stellar_base_url.rstrip("/")
        self._api_key = settings.stellar_cases_api_key
        self._timeout = httpx.Timeout(settings.connector_http_timeout_seconds)
        self._verify = settings.connector_tls_verify
        self._tenant_id = (settings.stellar_tenant_id or "").strip() or None
        self._jwt: str | None = None

    async def update_case(self, case_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", f"cases/{case_id}", json=body)

    async def add_case_comment(self, case_id: str, comment: str) -> dict[str, Any]:
        text = str(comment or "").strip()
        if not text:
            raise ValueError("comment text is required")
        return await self._request("POST", f"cases/{case_id}/comments", json={"comment": text})

    async def _request(self, method: str, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        jwt = await self._ensure_jwt()
        url = f"{self._base}/connect/api/v1/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {jwt}"}
        params = {"tenant_id": self._tenant_id} if self._tenant_id else None
        async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
            response = await client.request(method, url, headers=headers, json=json, params=params)
            if response.status_code == 401:
                self._jwt = None
                jwt = await self._ensure_jwt()
                headers = {"Authorization": f"Bearer {jwt}"}
                response = await client.request(method, url, headers=headers, json=json, params=params)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Stellar Cases API {method} {path} HTTP {response.status_code}: {response.text[:500]}",
                request=response.request,
                response=response,
            )
        if not response.content:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def _ensure_jwt(self) -> str:
        if self._jwt:
            return self._jwt
        url = f"{self._base}/connect/api/v1/access_token"
        async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {self._api_key}"}
            )
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Stellar access_token HTTP {response.status_code}: {response.text[:500]}",
                request=response.request,
                response=response,
            )
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Stellar access_token response missing access_token")
        self._jwt = token.strip()
        return self._jwt
