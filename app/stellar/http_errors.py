"""Classify Stellar HTTP / transport failures for logging and automation."""

from __future__ import annotations

import httpx

from app.stellar.errors import StellarAPIError, infer_error_type


def wrap_transport_error(
    exc: Exception,
    *,
    method: str,
    path: str,
    timeout_seconds: float,
) -> StellarAPIError:
    if isinstance(exc, StellarAPIError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return StellarAPIError(
            f"Stellar timeout after {timeout_seconds}s for {method} {path}",
            error_type="timeout",
        )
    if isinstance(exc, httpx.RequestError):
        return StellarAPIError(
            f"Stellar request error for {method} {path}: {exc}",
            error_type="transport",
        )
    return StellarAPIError(
        f"Stellar unexpected error for {method} {path}: {exc}",
        error_type="transport",
    )


def stellar_error_dict(
    exc: StellarAPIError,
    *,
    source_id: str,
    scope: str = "stellar",
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "scope": scope,
        "error": str(exc),
        "detail": str(exc),
        "http_status": exc.status_code,
        "body": exc.body,
        "error_type": exc.error_type,
    }


def inbound_stellar_unreachable(out: dict[str, object]) -> bool:
    """True when poll cycle failed before case processing (skip writeback)."""
    if out.get("ok"):
        return False
    if out.get("error") == "stellar":
        return True
    errors = out.get("errors")
    if not isinstance(errors, list):
        return False
    return any(isinstance(e, dict) and e.get("scope") == "stellar" for e in errors)


__all__ = [
    "infer_error_type",
    "wrap_transport_error",
    "stellar_error_dict",
    "inbound_stellar_unreachable",
]
