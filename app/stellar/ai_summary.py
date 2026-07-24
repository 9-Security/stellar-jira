"""Retrieve and format Stellar Cyber's native AI Case Summary through MCP."""

from __future__ import annotations

import json
from typing import Any

import httpx


class StellarAISummaryError(RuntimeError):
    """Raised when the read-only Stellar MCP workflow fails."""


def _json_text_payload(response: dict[str, Any]) -> Any:
    result = response.get("result")
    if not isinstance(result, dict):
        error = response.get("error")
        raise StellarAISummaryError(f"Stellar MCP error: {error or 'missing result'}")
    if result.get("isError"):
        raise StellarAISummaryError("Stellar MCP tool returned an error")
    content = result.get("content")
    if not isinstance(content, list):
        return result
    for item in content:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        text = item["text"].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return result


def extract_ai_case_triage(payload: Any) -> dict[str, Any] | None:
    """Return populated ``ai_case_triage`` or None while Stellar is still preparing it."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    ai_summary = data.get("aiSummary")
    if not isinstance(ai_summary, dict):
        return None
    triage = ai_summary.get("ai_case_triage")
    return triage if isinstance(triage, dict) and triage else None


def ai_summary_triage_state(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data")
    ai_summary = data.get("aiSummary") if isinstance(data, dict) else None
    if not isinstance(ai_summary, dict):
        return ""
    return str(ai_summary.get("triage_state") or "").strip()


def format_ai_summary_comment(payload: dict[str, Any]) -> str:
    """Build a concise Jira comment while preserving the full payload separately."""
    triage = extract_ai_case_triage(payload) or {}
    summary = triage.get("summary")
    summary = summary if isinstance(summary, dict) else {}

    lines = ["Stellar Cyber AI Summary", ""]
    concise = str(summary.get("concise_summary") or "").strip()
    verdict = str(triage.get("verdict") or "").strip()
    reasoning = str(triage.get("verdict_reasoning") or "").strip()
    if concise:
        lines.extend(["摘要：", concise, ""])
    if verdict:
        lines.append(f"判定：{verdict}")
    if reasoning:
        lines.extend(["判定理由：", reasoning])
    if verdict or reasoning:
        lines.append("")

    sections = (
        ("事件時間軸", "timeline"),
        ("調查假設", "hypothesis"),
        ("關鍵實體與關聯", "key_entities_and_relations"),
        ("建議處置", "recommendations"),
    )
    for label, key in sections:
        value = str(summary.get(key) or "").strip()
        if value:
            lines.extend([f"{label}：", value, ""])

    state = ai_summary_triage_state(payload)
    if state:
        lines.append(f"Triage state: {state}")
    lines.extend(["", "（Stellar Cyber 原生 AI 分析，請由 SOC 人員覆核後執行。）"])
    return "\n".join(lines).strip()[:32000]


class StellarAISummaryClient:
    """Minimal read-only MCP client for ``getCaseDetail(include=aiSummary)``."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        verify_tls: bool = True,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/mcp/"
        self._api_key = api_key
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            verify=verify_tls,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        self._request_id = 0
        self._initialized = False

    async def __aenter__(self) -> StellarAISummaryClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        response = await self._http.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            },
        )
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._http.headers["mcp-session-id"] = session_id
        if response.status_code >= 400:
            raise StellarAISummaryError(
                f"Stellar MCP HTTP {response.status_code} for {method}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise StellarAISummaryError("Stellar MCP returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise StellarAISummaryError("Stellar MCP returned an invalid response")
        return payload

    async def _initialize(self) -> None:
        if self._initialized:
            return
        response = await self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "stellar-jira", "version": "1"},
            },
        )
        _json_text_payload(response)
        self._initialized = True

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self._initialize()
        response = await self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        return _json_text_payload(response)

    async def get_case_ai_summary(
        self,
        *,
        ticket_id: str = "",
        case_id: str = "",
    ) -> dict[str, Any]:
        token_payload = await self._call_tool("get_access_token", {})
        if isinstance(token_payload, dict):
            access_token = str(
                token_payload.get("access_token") or token_payload.get("token") or ""
            ).strip()
        else:
            access_token = str(token_payload or "").strip()
        if not access_token:
            raise StellarAISummaryError("Stellar MCP did not return an access token")

        arguments: dict[str, Any] = {
            "access_token": access_token,
            "include": "aiSummary",
        }
        if str(ticket_id or "").strip():
            arguments["ticket_id"] = str(ticket_id).strip()
        elif str(case_id or "").strip():
            arguments["id"] = str(case_id).strip()
        else:
            raise ValueError("ticket_id or case_id is required")

        payload = await self._call_tool("getCaseDetail", arguments)
        if not isinstance(payload, dict):
            raise StellarAISummaryError("Stellar MCP case detail response is not an object")
        return payload
