"""JWT access token from Stellar Cyber API key (refresh token)."""

from __future__ import annotations

import httpx

from app.stellar.errors import StellarAPIError
from app.stellar.http_errors import wrap_transport_error


async def fetch_access_token(
    *,
    base_url: str,
    api_key: str,
    timeout_seconds: float,
    verify_tls: bool,
) -> str:
    """
    Exchange API key for a short-lived JWT.

    See https://docs.stellarcyber.ai/5.5.x/Using/API/API-Auth.htm
    POST https://{host}/connect/api/v1/access_token
    Header: Authorization: Bearer {api_key}
    """
    host = base_url.rstrip("/")
    url = f"{host}/connect/api/v1/access_token"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), verify=verify_tls) as client:
            response = await client.post(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as e:
        raise wrap_transport_error(
            e, method="POST", path="access_token", timeout_seconds=timeout_seconds
        ) from e
    if response.status_code >= 400:
        raise StellarAPIError(
            f"Stellar access_token HTTP {response.status_code}: {response.text[:500]}",
            status_code=response.status_code,
            body=response.text[:2000],
            error_type="auth" if response.status_code in (401, 403) else None,
        )
    try:
        payload = response.json()
    except ValueError as e:
        raise StellarAPIError("Stellar access_token: invalid JSON response", error_type="transport") from e
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise StellarAPIError("Stellar access_token: missing access_token in response", error_type="auth")
    return token.strip()
