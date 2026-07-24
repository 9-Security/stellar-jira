"""Async HTTP client for Stellar Cyber /connect/api/v1 (Cases API)."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlencode

import httpx

from app.stellar.auth import fetch_access_token
from app.stellar.errors import StellarAPIError
from app.stellar.http_errors import wrap_transport_error


class StellarClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        verify_tls: bool = True,
        tenant_id: str | None = None,
        http_max_retries: int = 0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._timeout_seconds = float(timeout_seconds)
        self._verify_tls = verify_tls
        self._tenant_id = tenant_id.strip() if tenant_id and tenant_id.strip() else None
        self._http_max_retries = max(0, int(http_max_retries))
        self._jwt: str | None = None
        self._http: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> StellarClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout, verify=self._verify_tls)
        return self._http

    async def _ensure_jwt(self) -> str:
        self._jwt = await fetch_access_token(
            base_url=self._base,
            api_key=self._api_key,
            timeout_seconds=self._timeout.read or 60.0,
            verify_tls=self._verify_tls,
        )
        return self._jwt

    def _auth_headers(self, jwt: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {jwt}"}

    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        attempts = 1 + (self._http_max_retries if method.upper() == "GET" else 0)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._request_once(method, path, params=params)
            except StellarAPIError as e:
                last_exc = e
                retryable = e.error_type in ("timeout", "http_5xx", "transport")
                if not retryable or attempt >= attempts - 1:
                    raise
                await asyncio.sleep(min(2.0**attempt, 8.0))
            except httpx.HTTPError as e:
                last_exc = e
                wrapped = wrap_transport_error(
                    e,
                    method=method,
                    path=path,
                    timeout_seconds=self._timeout_seconds,
                )
                if wrapped.error_type not in ("timeout", "transport") or attempt >= attempts - 1:
                    raise wrapped from e
                last_exc = wrapped
                await asyncio.sleep(min(2.0**attempt, 8.0))
        if last_exc:
            raise last_exc
        raise StellarAPIError(f"Stellar request failed for {method} {path}", error_type="transport")

    async def _request_once(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        jwt = await self._ensure_jwt()
        url = f"{self._base}/connect/api/v1/{path.lstrip('/')}"
        if params:
            q = {k: v for k, v in params.items() if v is not None}
            if q:
                url = f"{url}?{urlencode(q)}"
        try:
            response = await self._client().request(method, url, headers=self._auth_headers(jwt))
        except httpx.HTTPError as e:
            raise wrap_transport_error(
                e,
                method=method,
                path=path,
                timeout_seconds=self._timeout_seconds,
            ) from e
        if response.status_code == 401:
            self._jwt = None
            jwt = await self._ensure_jwt()
            response = await self._client().request(method, url, headers=self._auth_headers(jwt))
        if response.status_code >= 400:
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = response.text[:2000]
            raise StellarAPIError(
                f"Stellar HTTP {response.status_code} for {method} {path}",
                status_code=response.status_code,
                body=body,
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as e:
            raise StellarAPIError("Stellar: invalid JSON response", status_code=response.status_code) from e

    @staticmethod
    def extract_cases_list(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        cases = data.get("cases")
        if isinstance(cases, list):
            return [c for c in cases if isinstance(c, dict)]
        return []

    @staticmethod
    def extract_case_one(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("case"), dict):
                return data["case"]
            cases = data.get("cases")
            if isinstance(cases, list) and cases and isinstance(cases[0], dict):
                return cases[0]
            if data.get("_id") is not None:
                return data
        if payload.get("_id") is not None:
            return payload
        return None

    async def list_cases(
        self,
        *,
        limit: int = 1,
        skip: int = 0,
        sort: str = "modified_at",
        order: str = "desc",
        status: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": max(1, min(limit, 500)),
            "skip": max(0, skip),
            "sort": sort,
            "order": order,
        }
        tid = tenant_id or self._tenant_id
        if tid:
            params["tenant_id"] = tid
        if status:
            params["status"] = status
        return await self._request("GET", "cases", params=params)

    async def list_all_cases(
        self,
        *,
        page_size: int = 500,
        max_pages: int = 200,
        sort: str = "created_at",
        order: str = "asc",
        status: str | None = None,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Paginate GET /cases until empty or ``max_pages`` reached. Second value = truncated."""
        page_size = max(1, min(page_size, 500))
        collected: list[dict[str, Any]] = []
        truncated = False
        skip = 0
        for page_idx in range(max_pages):
            raw = await self.list_cases(
                limit=page_size,
                skip=skip,
                sort=sort,
                order=order,
                status=status,
                tenant_id=tenant_id,
            )
            batch = self.extract_cases_list(raw)
            if not batch:
                break
            collected.extend(batch)
            skip += len(batch)
            if len(batch) < page_size:
                break
            if page_idx == max_pages - 1:
                truncated = True
        return collected, truncated

    async def fetch_cases_modified_since(
        self,
        since_ms: int,
        *,
        page_size: int = 50,
        max_pages: int = 40,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """
        Return cases with ``modified_at`` >= ``since_ms`` (newest-first pagination).
        Second value is True if pagination stopped early due to ``max_pages``.
        """
        page_size = max(1, min(page_size, 500))
        collected: list[dict[str, Any]] = []
        truncated = False
        skip = 0
        for page_idx in range(max_pages):
            raw = await self.list_cases(
                limit=page_size,
                skip=skip,
                sort="modified_at",
                order="desc",
                tenant_id=tenant_id,
            )
            batch = self.extract_cases_list(raw)
            if not batch:
                break
            below_window = False
            for case in batch:
                mid = int(case.get("modified_at") or 0)
                if mid >= since_ms:
                    collected.append(case)
                elif mid > 0:
                    below_window = True
            if below_window:
                break
            skip += page_size
            if len(batch) < page_size:
                break
            if page_idx == max_pages - 1:
                truncated = True
        collected.sort(key=lambda x: int(x.get("modified_at") or 0))
        return collected, truncated

    async def fetch_cases_created_since(
        self,
        since_ms: int,
        *,
        page_size: int = 50,
        max_pages: int = 40,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return cases with ``created_at`` >= ``since_ms`` (newest-first pagination)."""
        page_size = max(1, min(page_size, 500))
        collected: list[dict[str, Any]] = []
        truncated = False
        skip = 0
        for page_idx in range(max_pages):
            raw = await self.list_cases(
                limit=page_size,
                skip=skip,
                sort="created_at",
                order="desc",
                tenant_id=tenant_id,
            )
            batch = self.extract_cases_list(raw)
            if not batch:
                break
            below_window = False
            for case in batch:
                created = int(case.get("created_at") or 0)
                if created >= since_ms:
                    collected.append(case)
                elif created > 0:
                    below_window = True
            if below_window:
                break
            skip += page_size
            if len(batch) < page_size:
                break
            if page_idx == max_pages - 1:
                truncated = True
        collected.sort(key=lambda x: int(x.get("created_at") or 0))
        return collected, truncated

    async def get_case(self, case_id: str) -> dict[str, Any]:
        return await self._request("GET", f"cases/{case_id}")

    async def get_case_alerts(self, case_id: str) -> dict[str, Any]:
        return await self._request("GET", f"cases/{case_id}/alerts")

    async def get_case_observables(self, case_id: str) -> dict[str, Any]:
        return await self._request("GET", f"cases/{case_id}/observables")

    async def get_case_activities(self, case_id: str) -> dict[str, Any]:
        return await self._request("GET", f"cases/{case_id}/activities")

    async def get_case_summary(self, case_id: str) -> dict[str, Any]:
        return await self._request("GET", f"cases/{case_id}/summary")

    async def update_case(self, case_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """PUT severity, status, assignee, tags, description (see Stellar Case Update API)."""
        result = await self._put_json(case_id, body)
        return result if isinstance(result, dict) else {}

    async def get_case_comments(self, case_id: str) -> list[dict[str, Any]]:
        raw = await self._request("GET", f"cases/{case_id}/comments")
        if not isinstance(raw, dict):
            return []
        data = raw.get("data")
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict)]
        return []

    async def add_case_comment(self, case_id: str, text: str) -> dict[str, Any]:
        """POST ``{"comment": "..."}`` to ``/cases/{id}/comments``."""
        comment = str(text or "").strip()
        if not comment:
            raise ValueError("comment text is required")
        result = await self._post_json(f"cases/{case_id}/comments", {"comment": comment})
        return result if isinstance(result, dict) else {}

    async def _post_json(self, path: str, body: dict[str, Any]) -> Any:
        jwt = await self._ensure_jwt()
        url = f"{self._base}/connect/api/v1/{path.lstrip('/')}"
        try:
            response = await self._client().post(url, headers=self._auth_headers(jwt), json=body)
        except httpx.HTTPError as e:
            raise wrap_transport_error(
                e, method="POST", path=path, timeout_seconds=self._timeout_seconds
            ) from e
        if response.status_code == 401:
            self._jwt = None
            jwt = await self._ensure_jwt()
            response = await self._client().post(url, headers=self._auth_headers(jwt), json=body)
        if response.status_code >= 400:
            body_out: Any
            try:
                body_out = response.json()
            except ValueError:
                body_out = response.text[:2000]
            raise StellarAPIError(
                f"Stellar HTTP {response.status_code} for POST {path}",
                status_code=response.status_code,
                body=body_out,
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as e:
            raise StellarAPIError("Stellar: invalid JSON response", status_code=response.status_code) from e

    async def _put_json(self, case_id: str, body: dict[str, Any]) -> Any:
        jwt = await self._ensure_jwt()
        url = f"{self._base}/connect/api/v1/cases/{case_id}"
        try:
            response = await self._client().put(url, headers=self._auth_headers(jwt), json=body)
        except httpx.HTTPError as e:
            raise wrap_transport_error(
                e, method="PUT", path=f"cases/{case_id}", timeout_seconds=self._timeout_seconds
            ) from e
        if response.status_code == 401:
            self._jwt = None
            jwt = await self._ensure_jwt()
            response = await self._client().put(url, headers=self._auth_headers(jwt), json=body)
        if response.status_code >= 400:
            body_out: Any
            try:
                body_out = response.json()
            except ValueError:
                body_out = response.text[:2000]
            raise StellarAPIError(
                f"Stellar HTTP {response.status_code} for PUT cases/{case_id}",
                status_code=response.status_code,
                body=body_out,
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as e:
            raise StellarAPIError("Stellar: invalid JSON response", status_code=response.status_code) from e

    async def fetch_case_bundle(self, case_id: str) -> dict[str, Any]:
        """Case + alerts + observables + activities + summary (best-effort)."""
        bundle: dict[str, Any] = {"case_id": case_id}
        bundle["case"] = self.extract_case_one(await self.get_case(case_id))
        for key, coro in (
            ("alerts", self.get_case_alerts(case_id)),
            ("observables", self.get_case_observables(case_id)),
            ("activities", self.get_case_activities(case_id)),
            ("summary", self.get_case_summary(case_id)),
        ):
            try:
                bundle[key] = await coro
            except StellarAPIError as e:
                bundle[key] = {"error": str(e), "http_status": e.status_code, "body": e.body}
        return bundle
