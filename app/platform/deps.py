"""FastAPI dependencies for platform auth."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import PlatformSettings, get_platform_settings
from app.platform.roles import UserRole, is_platform_role
from app.platform.totp_policy import session_blocks_without_totp
from app.platform.security import decode_token
from app.platform.session_cookie import read_session_token
from app.platform.store import PlatformStore

_bearer = HTTPBearer(auto_error=False)


def get_platform_store(
    settings: PlatformSettings = Depends(get_platform_settings),
) -> PlatformStore:
    store = PlatformStore(settings.db_path_resolved())
    store.init()
    return store


def _client_ip(request: Request, settings: PlatformSettings) -> str | None:
    if not settings.platform_trust_proxy_headers:
        return request.client.host if request.client else None
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip() or None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


class CurrentUser:
    def __init__(self, user: dict[str, Any], claims: dict[str, Any]) -> None:
        self.user = user
        self.claims = claims

    @property
    def id(self) -> str:
        return str(self.user["id"])

    @property
    def role(self) -> str:
        return str(self.user["role"])

    @property
    def tenant_source_id(self) -> str | None:
        raw = self.user.get("tenant_source_id")
        return str(raw).strip() if raw else None

    @property
    def totp_setup_required(self) -> bool:
        return bool(self.claims.get("totp_setup_required"))

    def is_platform_scope(self) -> bool:
        return is_platform_role(self.role)

    def can_access_tenant(self, tenant_source_id: str | None) -> bool:
        if self.is_platform_scope():
            return True
        if not tenant_source_id:
            return False
        return self.tenant_source_id == str(tenant_source_id).strip()


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: PlatformSettings = Depends(get_platform_settings),
    store: PlatformStore = Depends(get_platform_store),
) -> CurrentUser:
    if not settings.platform_enabled:
        raise HTTPException(status_code=503, detail="Platform auth is disabled")

    token: str | None = None
    if credentials is not None and credentials.credentials:
        token = credentials.credentials.strip() or None
    if not token:
        token = read_session_token(request, settings)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        claims = decode_token(settings, token, expected_type="access")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    user = store.get_user_by_id(str(claims.get("sub") or ""))
    if user is None or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return CurrentUser(user=user, claims=claims)


async def require_full_session(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    settings: PlatformSettings = Depends(get_platform_settings),
) -> CurrentUser:
    if current.totp_setup_required:
        raise HTTPException(
            status_code=403,
            detail="TOTP setup required; complete /v1/auth/totp/setup and /confirm",
        )
    if session_blocks_without_totp(current.user):
        raise HTTPException(status_code=403, detail="TOTP is required for this account")
    return current


def require_roles(*allowed: UserRole | str):
    allowed_set = {str(r) for r in allowed}

    async def _dep(
        current: Annotated[CurrentUser, Depends(require_full_session)],
    ) -> CurrentUser:
        if current.role not in allowed_set:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current

    return _dep


def audit_request_ip(request: Request, settings: PlatformSettings | None = None) -> str | None:
    if settings is None:
        settings = get_platform_settings()
    return _client_ip(request, settings)
