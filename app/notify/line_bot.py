"""LINE Messaging API push notifications."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import NotifySettings, get_notify_settings

logger = logging.getLogger(__name__)

LINE_PUSH_API_URL = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"
LINE_FOLLOWERS_API_URL = "https://api.line.me/v2/bot/followers/ids"
LINE_PROFILE_API_URL = "https://api.line.me/v2/bot/profile"
LINE_TEXT_MAX_LEN = 5000
# LINE user/group/room IDs are exactly 33 chars: U/C/R + 32 hex digits.
_LINE_ID_RE = re.compile(r"^[UCR][0-9a-fA-F]{32}$")


_LINE_ID_EXAMPLE = "Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def line_recipient_id_hint(recipient: str) -> str | None:
    value = str(recipient or "").strip()
    if not value:
        return "empty recipient"
    if len(value) < 33:
        return (
            f"{value!r} is too short ({len(value)} chars, need 33); "
            f"copy the full ID from the bot webhook reply (example shape: {_LINE_ID_EXAMPLE})"
        )
    if len(value) > 33:
        return f"{value!r} is too long ({len(value)} chars); LINE IDs are exactly 33 characters"
    if value[0] not in {"U", "C", "R"}:
        return f"{value!r} must start with U (user), C (group), or R (room)"
    if not _LINE_ID_RE.match(value):
        return f"{value!r} is not a valid LINE recipient ID format"
    return None


def parse_line_recipient_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,;\s]+", raw.strip())
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        recipient = part.strip()
        if not recipient:
            continue
        if recipient in seen:
            continue
        if not _LINE_ID_RE.match(recipient):
            hint = line_recipient_id_hint(recipient)
            logger.warning("skipping invalid LINE recipient id: %s", hint or recipient)
            continue
        seen.add(recipient)
        out.append(recipient)
    return out


def _truncate_line_text(text: str, *, max_len: int = LINE_TEXT_MAX_LEN) -> str:
    body = str(text or "").strip()
    if len(body) <= max_len:
        return body
    suffix = "\n...(訊息已截斷)"
    keep = max_len - len(suffix)
    if keep < 1:
        return body[:max_len]
    return body[:keep] + suffix


def _line_auth_headers(settings: NotifySettings) -> dict[str, str]:
    token = (settings.line_channel_access_token or "").strip()
    if not token:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _line_get_json(
    settings: NotifySettings,
    url: str,
    *,
    params: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    timeout = float(settings.line_notify_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers=_line_auth_headers(settings), params=params)
    if resp.status_code >= 400:
        detail = resp.text.strip() or resp.reason_phrase
        raise ValueError(f"LINE API {resp.status_code}: {detail}")
    data = resp.json()
    return data if isinstance(data, dict) else {"raw": data}


async def list_line_follower_ids(
    settings: NotifySettings | None = None,
    *,
    limit: int = 1000,
) -> list[str]:
    """Return user IDs of accounts that added this bot as a friend."""
    st = settings or get_notify_settings()
    if not st.line_configured:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is not set")

    ids: list[str] = []
    start: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": min(max(limit - len(ids), 1), 1000)}
        if start:
            params["start"] = start
        data = await _line_get_json(st, LINE_FOLLOWERS_API_URL, params=params)
        batch = data.get("userIds")
        if isinstance(batch, list):
            ids.extend(str(user_id).strip() for user_id in batch if str(user_id).strip())
        next_start = data.get("next")
        if not next_start or len(ids) >= limit:
            break
        start = str(next_start)
    return ids[:limit]


async def get_line_user_profile(
    user_id: str,
    settings: NotifySettings | None = None,
) -> dict[str, Any]:
    st = settings or get_notify_settings()
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    return await _line_get_json(st, f"{LINE_PROFILE_API_URL}/{uid}")


async def reply_line_text(
    settings: NotifySettings,
    *,
    reply_token: str,
    text: str,
) -> dict[str, Any]:
    token = str(reply_token or "").strip()
    if not token:
        raise ValueError("reply_token is required")
    payload = {
        "replyToken": token,
        "messages": [{"type": "text", "text": _truncate_line_text(text)}],
    }
    timeout = float(settings.line_notify_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            LINE_REPLY_API_URL,
            headers=_line_auth_headers(settings),
            json=payload,
        )
    if resp.status_code >= 400:
        detail = resp.text.strip() or resp.reason_phrase
        raise ValueError(f"LINE API {resp.status_code}: {detail}")
    if not resp.content:
        return {"ok": True}
    data = resp.json()
    return data if isinstance(data, dict) else {"raw": data}


async def push_line_text(
    settings: NotifySettings,
    *,
    to_id: str,
    text: str,
) -> dict[str, Any]:
    token = (settings.line_channel_access_token or "").strip()
    if not token:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is not set")
    recipient = str(to_id or "").strip()
    if not recipient:
        raise ValueError("no LINE recipient")
    id_error = line_recipient_id_hint(recipient)
    if id_error:
        raise ValueError(f"invalid LINE recipient: {id_error}")

    payload = {
        "to": recipient,
        "messages": [{"type": "text", "text": _truncate_line_text(text)}],
    }
    timeout = float(settings.line_notify_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            LINE_PUSH_API_URL,
            headers=_line_auth_headers(settings),
            json=payload,
        )
    if resp.status_code >= 400:
        detail = resp.text.strip() or resp.reason_phrase
        raise ValueError(f"LINE API {resp.status_code}: {detail}")
    if not resp.content:
        return {"ok": True}
    data = resp.json()
    return data if isinstance(data, dict) else {"raw": data}


async def send_line_notify(
    *,
    to_ids: list[str],
    subject: str,
    body_text: str,
    settings: NotifySettings | None = None,
) -> dict[str, Any]:
    st = settings or get_notify_settings()
    if not to_ids:
        return {"skipped": True, "reason": "no_recipients"}
    if not st.line_configured:
        return {"skipped": True, "reason": "not_configured"}

    subject_line = str(subject or "").strip()
    body = str(body_text or "").strip()
    text = f"{subject_line}\n\n{body}" if subject_line and body else subject_line or body
    if not text:
        return {"skipped": True, "reason": "empty_message"}

    sent_to: list[str] = []
    errors: list[dict[str, str]] = []
    for recipient in to_ids:
        try:
            await push_line_text(st, to_id=recipient, text=text)
            sent_to.append(recipient)
        except Exception as e:
            logger.warning("LINE notify failed recipient=%s: %s", recipient, e)
            errors.append({"recipient": recipient, "error": str(e)})

    if sent_to and not errors:
        return {"sent": True, "provider": "line", "recipients": sent_to}
    if sent_to:
        return {
            "sent": True,
            "provider": "line",
            "recipients": sent_to,
            "partial": True,
            "errors": errors,
        }
    return {"sent": False, "provider": "line", "errors": errors}
