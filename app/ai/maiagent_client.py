"""MaiAgent API clients (side-path trial only; not used by production notify).

Tenant example (Sungcheng):
  POST https://api.sungcheng.org/api/chatbots/{chatbotId}/completions/
  Authorization: Api-Key <key>

Public SaaS often uses ``https://api.maiagent.ai/api/v1`` instead — set
``MAIAGENT_BASE_URL`` accordingly (no trailing slash; we append ``/chatbots/...``).
"""

from __future__ import annotations

from typing import Any

import httpx

# JJNET / Sungcheng private MaiAgent — override via MAIAGENT_BASE_URL if needed
DEFAULT_BASE_URL = "https://api.sungcheng.org/api"


class MaiAgentAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _auth_headers(api_key: str, *, scheme: str) -> dict[str, str]:
    key = (api_key or "").strip()
    if scheme == "bearer":
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # Historical chatbot docs
    return {"Authorization": f"Api-Key {key}", "Content-Type": "application/json"}


def _raise_for_status(resp: httpx.Response, *, mode: str) -> None:
    if resp.status_code < 400:
        return
    detail = (resp.text or "").strip() or resp.reason_phrase
    hint = ""
    if resp.status_code == 401:
        hint = (
            " | hint: check MAIAGENT_BASE_URL (Sungcheng: https://api.sungcheng.org/api) "
            "and that Authorization is exactly `Api-Key <full-key>`. "
            "Wrong host (api.maiagent.ai) or incomplete key both look like this 401."
        )
    raise MaiAgentAPIError(
        f"MaiAgent API {resp.status_code} ({mode}): {detail}{hint}",
        status_code=resp.status_code,
    )


async def chatbot_completion(
    *,
    api_key: str,
    chatbot_id: str,
    message: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 60.0,
    conversation_id: str | None = None,
    is_streaming: bool = False,
    auth_scheme: str = "api-key",
) -> dict[str, Any]:
    """Send one synchronous message to a MaiAgent chatbot."""
    key = (api_key or "").strip()
    bot = (chatbot_id or "").strip()
    if not key:
        raise ValueError("MAIAGENT_API_KEY is not set")
    if not bot:
        raise ValueError("MAIAGENT_CHATBOT_ID is not set")
    root = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url = f"{root}/chatbots/{bot}/completions/"
    body: dict[str, Any] = {
        "message": {"content": str(message or ""), "attachments": []},
        "is_streaming": bool(is_streaming),
    }
    if conversation_id:
        body["conversation"] = conversation_id
    scheme = "bearer" if auth_scheme.strip().lower() in {"bearer", "openai"} else "api-key"
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
        resp = await client.post(url, headers=_auth_headers(key, scheme=scheme), json=body)
    _raise_for_status(resp, mode="chatbot")
    data = resp.json()
    if not isinstance(data, dict):
        raise MaiAgentAPIError("MaiAgent API returned non-object JSON")
    content = data.get("content")
    if content is None:
        content = data.get("message") or data.get("reply") or ""
    conv = (
        data.get("conversationId")
        or data.get("conversation_id")
        or data.get("conversation")
        or ""
    )
    return {
        "content": str(content or ""),
        "conversation_id": str(conv or ""),
        "raw": data,
    }


async def openai_chat_completion(
    *,
    api_key: str,
    message: str,
    system_prompt: str = "",
    model: str = "gpt-4o-mini",
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """OpenAI-compatible chat completions via MaiAgent AI Gateway."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("MAIAGENT_API_KEY is not set")
    root = (base_url or DEFAULT_BASE_URL).rstrip("/")
    # Accept either .../api/v1 or .../api/v1/chat/completions already
    if root.endswith("/chat/completions"):
        url = root
    else:
        url = f"{root}/chat/completions"
    messages: list[dict[str, str]] = []
    if (system_prompt or "").strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": str(message or "")})
    payload: dict[str, Any] = {
        "model": (model or "gpt-4o-mini").strip(),
        "temperature": 0.35,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
        resp = await client.post(url, headers=_auth_headers(key, scheme="bearer"), json=payload)
    _raise_for_status(resp, mode="openai")
    data = resp.json()
    if not isinstance(data, dict):
        raise MaiAgentAPIError("MaiAgent openai mode returned non-object JSON")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        # Some gateways return content at top level
        content = data.get("content")
        if isinstance(content, str):
            return {"content": content, "conversation_id": "", "raw": data, "model": model}
        raise MaiAgentAPIError("MaiAgent openai mode returned no choices")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, str):
        raise MaiAgentAPIError("MaiAgent openai mode returned empty message content")
    return {
        "content": content,
        "conversation_id": "",
        "raw": data,
        "model": data.get("model") or model,
    }
