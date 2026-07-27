"""Validate Stellar XDR webhook responses before marking events as sent."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def stellar_ingest_succeeded(response: httpx.Response) -> bool:
    if response.status_code >= 400:
        return False
    if not response.content:
        return True
    try:
        payload = response.json()
    except ValueError:
        logger.warning("Stellar ingest returned non-JSON body with status %s", response.status_code)
        return response.status_code < 400
    return _json_indicates_success(payload)


def _json_indicates_success(payload: Any) -> bool:
    if payload is None:
        return True
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, (int, float)):
        return payload >= 0
    if isinstance(payload, str):
        lowered = payload.strip().lower()
        if lowered in ("ok", "success", "accepted"):
            return True
        if lowered in ("error", "failed", "failure"):
            return False
        return True
    if not isinstance(payload, dict):
        return True

    for key in ("error", "errors", "failure", "failed"):
        if key in payload and payload[key]:
            return False

    for key in ("success", "ok", "accepted"):
        if key in payload and payload[key] is False:
            return False

    status = payload.get("status")
    if isinstance(status, str):
        lowered = status.lower()
        if lowered in ("error", "failed", "failure"):
            return False
        if lowered in ("ok", "success", "accepted"):
            return True

    code = payload.get("code")
    if isinstance(code, int) and code < 0:
        return False

    message = payload.get("message")
    if isinstance(message, str) and message.strip().lower().startswith("error"):
        return False

    return True


def format_ingest_failure(response: httpx.Response) -> str:
    body = response.text[:500]
    try:
        payload = response.json()
        body = json.dumps(payload, ensure_ascii=False)[:500]
    except ValueError:
        pass
    return f"HTTP {response.status_code}: {body}"
