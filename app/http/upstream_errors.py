"""Sanitize upstream API error payloads before returning them to HTTP clients."""

from __future__ import annotations

import json
from typing import Any

_REDACT_KEY_FRAGMENTS = ("key", "token", "password", "secret", "authorization", "credential")


def _truncate_text(s: str, *, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


def sanitize_upstream_body(body: Any, *, max_len: int = 500, max_depth: int = 4) -> Any:
    """Return a client-safe snapshot of an upstream error body."""

    def walk(val: Any, depth: int) -> Any:
        if depth > max_depth:
            return "…"
        if val is None or isinstance(val, (bool, int, float)):
            return val
        if isinstance(val, str):
            return _truncate_text(val, max_len=max_len)
        if isinstance(val, list):
            items = [walk(x, depth + 1) for x in val[:20]]
            if len(val) > 20:
                items.append(f"…({len(val) - 20} more)")
            return items
        if isinstance(val, dict):
            out: dict[str, Any] = {}
            for k, v in list(val.items())[:30]:
                key = str(k)
                if any(frag in key.lower() for frag in _REDACT_KEY_FRAGMENTS):
                    out[key] = "<redacted>"
                else:
                    out[key] = walk(v, depth + 1)
            if len(val) > 30:
                out["…"] = f"{len(val) - 30} more keys"
            return out
        try:
            text = json.dumps(val, default=str)
        except TypeError:
            text = str(val)
        return _truncate_text(text, max_len=max_len)

    return walk(body, 0)


def upstream_error_detail(exc: BaseException, *, include_body: bool = True) -> dict[str, Any]:
    detail: dict[str, Any] = {"error": str(exc)}
    status = getattr(exc, "status_code", None)
    if status is not None:
        detail["http_status"] = status
    if include_body:
        body = getattr(exc, "body", None)
        if body is not None:
            detail["body"] = sanitize_upstream_body(body)
    return detail
