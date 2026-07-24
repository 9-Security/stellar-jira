"""Stellar API exceptions."""

from __future__ import annotations

from typing import Any


def infer_error_type(*, status_code: int | None, message: str) -> str:
    if status_code is not None:
        if status_code in (401, 403):
            return "auth"
        if status_code >= 500:
            return "http_5xx"
        if status_code >= 400:
            return "http_4xx"
    if "timeout" in message.lower():
        return "timeout"
    return "transport"


class StellarAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.error_type = error_type or infer_error_type(status_code=status_code, message=message)
