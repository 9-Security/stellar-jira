"""HttpOnly session cookie helpers for platform auth."""

from __future__ import annotations

from fastapi import Request, Response

from app.config import PlatformSettings


def _cookie_secure(request: Request, settings: PlatformSettings) -> bool:
    if settings.platform_cookie_secure is not None:
        return bool(settings.platform_cookie_secure)
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


def set_session_cookie(
    response: Response,
    request: Request,
    settings: PlatformSettings,
    token: str,
) -> None:
    response.set_cookie(
        key=settings.platform_session_cookie_name,
        value=token,
        httponly=True,
        secure=_cookie_secure(request, settings),
        samesite=settings.platform_cookie_samesite,
        max_age=int(settings.platform_session_ttl_hours) * 3600,
        path="/",
    )


def clear_session_cookie(
    response: Response,
    settings: PlatformSettings,
) -> None:
    response.delete_cookie(
        key=settings.platform_session_cookie_name,
        path="/",
    )


def read_session_token(request: Request, settings: PlatformSettings) -> str | None:
    raw = request.cookies.get(settings.platform_session_cookie_name)
    if not raw:
        return None
    token = str(raw).strip()
    return token or None
