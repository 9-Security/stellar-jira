"""HTTP helpers with transient-failure retries."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    **kwargs: object,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(max(1, max_attempts)):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts - 1:
                delay = min(2**attempt, 8)
                logger.warning(
                    "HTTP %s %s -> %s; retry in %ss (%s/%s)",
                    method,
                    url,
                    response.status_code,
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                await asyncio.sleep(delay)
                continue
            return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                delay = min(2**attempt, 8)
                logger.warning(
                    "HTTP %s %s transport error: %s; retry in %ss (%s/%s)",
                    method,
                    url,
                    exc,
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                await asyncio.sleep(delay)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("request_with_retry exhausted without response")
