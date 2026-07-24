"""Send email via Resend HTTP API (https://resend.com/docs/api-reference/emails/send-email)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import NotifySettings

RESEND_API_URL = "https://api.resend.com/emails"


async def send_email_resend(
    settings: NotifySettings,
    *,
    to_addrs: list[str],
    subject: str,
    body_text: str,
    cc_addrs: list[str] | None = None,
    bcc_addrs: list[str] | None = None,
) -> dict[str, Any]:
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        raise ValueError("RESEND_API_KEY is not set")
    from_addr = (settings.soc_notify_from or "").strip()
    if not from_addr:
        raise ValueError("SOC_NOTIFY_FROM is not set")
    if not to_addrs:
        raise ValueError("no recipients")

    payload: dict[str, Any] = {
        "from": from_addr,
        "to": to_addrs,
        "subject": subject,
        "text": body_text,
    }
    if cc_addrs:
        payload["cc"] = cc_addrs
    if bcc_addrs:
        payload["bcc"] = bcc_addrs

    async with httpx.AsyncClient(timeout=float(settings.smtp_timeout_seconds)) as client:
        resp = await client.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if resp.status_code >= 400:
        detail = resp.text.strip() or resp.reason_phrase
        raise ValueError(f"Resend API {resp.status_code}: {detail}")
    data = resp.json()
    return data if isinstance(data, dict) else {"raw": data}
