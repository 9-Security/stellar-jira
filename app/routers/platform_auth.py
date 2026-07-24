"""Platform authentication API (PRD v0.1 P0)."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.config import PlatformSettings, get_platform_settings
from app.platform.deps import (
    CurrentUser,
    audit_request_ip,
    get_current_user,
    get_platform_store,
    require_full_session,
)
from app.platform.roles import is_platform_role
from app.platform.rate_limit import record_auth_failure
from app.platform.session_cookie import clear_session_cookie, set_session_cookie
from app.platform.totp_policy import (
    login_requires_totp_setup,
    login_requires_totp_verify,
    session_blocks_without_totp,
)
from app.platform.schemas import (
    LoginRequest,
    LoginResponse,
    TotpConfirmRequest,
    TotpSetupResponse,
    TotpVerifyRequest,
    UserPublic,
)
from app.platform.security import (
    create_access_token,
    create_login_token,
    decode_token,
    new_totp_secret,
    totp_provisioning_uri,
    verify_password,
    verify_totp_code,
)
from app.platform.store import PlatformStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _settings() -> PlatformSettings:
    get_platform_settings.cache_clear()
    return get_platform_settings()


def _issue_session(
    response: Response,
    request: Request,
    settings: PlatformSettings,
    payload: LoginResponse,
) -> LoginResponse:
    token = payload.access_token
    if not token:
        return payload
    set_session_cookie(response, request, settings, token)
    if settings.platform_expose_bearer_token:
        return payload
    return payload.model_copy(update={"access_token": None})


def _login_response(
    settings: PlatformSettings,
    store: PlatformStore,
    user: dict[str, Any],
    *,
    totp_setup_required: bool,
) -> LoginResponse:
    token = create_access_token(
        settings,
        user_id=str(user["id"]),
        role=str(user["role"]),
        tenant_source_id=user.get("tenant_source_id"),
        totp_setup_required=totp_setup_required,
    )
    return LoginResponse(
        access_token=token,
        requires_totp=False,
        totp_setup_required=totp_setup_required,
        user=store.public_user(user),
    )


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: PlatformSettings = Depends(_settings),
    store: PlatformStore = Depends(get_platform_store),
) -> LoginResponse:
    if not settings.platform_enabled:
        raise HTTPException(status_code=503, detail="Platform auth is disabled")

    ip = audit_request_ip(request, settings)
    user = store.get_user_by_email(body.email)
    if user is None or not verify_password(body.password, str(user.get("password_hash") or "")):
        record_auth_failure(
            ip,
            email=body.email,
            max_attempts=settings.platform_login_rate_limit_attempts,
            window_seconds=settings.platform_login_rate_limit_window_seconds,
        )
        store.record_audit(
            user_id=user["id"] if user else None,
            action="login_failed",
            ip_address=ip,
            detail={"email": body.email.strip().lower()},
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Account is disabled")

    if login_requires_totp_verify(user):
        login_token = create_login_token(settings, user_id=str(user["id"]))
        store.record_audit(user_id=user["id"], action="login_totp_required", ip_address=ip)
        return LoginResponse(
            requires_totp=True,
            login_token=login_token,
            user=store.public_user(user),
        )

    if login_requires_totp_setup(user):
        if not settings.platform_bootstrap_allow_password_only:
            raise HTTPException(status_code=403, detail="TOTP setup required before login")
        store.record_audit(user_id=user["id"], action="login_bootstrap", ip_address=ip)
        return _issue_session(
            response,
            request,
            settings,
            _login_response(settings, store, user, totp_setup_required=True),
        )

    store.record_audit(user_id=user["id"], action="login_success", ip_address=ip)
    return _issue_session(
        response,
        request,
        settings,
        _login_response(settings, store, user, totp_setup_required=False),
    )


@router.post("/totp/verify", response_model=LoginResponse)
def verify_totp_login(
    body: TotpVerifyRequest,
    request: Request,
    response: Response,
    settings: PlatformSettings = Depends(_settings),
    store: PlatformStore = Depends(get_platform_store),
) -> LoginResponse:
    if not settings.platform_enabled:
        raise HTTPException(status_code=503, detail="Platform auth is disabled")

    ip = audit_request_ip(request, settings)

    try:
        claims = decode_token(settings, body.login_token, expected_type="login")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired login token") from None

    user = store.get_user_by_id(str(claims.get("sub") or ""))
    if user is None or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    secret = str(user.get("totp_secret") or "")
    if not secret or not verify_totp_code(secret, body.code):
        record_auth_failure(
            ip,
            email=str(user.get("email") or ""),
            max_attempts=settings.platform_login_rate_limit_attempts,
            window_seconds=settings.platform_login_rate_limit_window_seconds,
        )
        store.record_audit(
            user_id=user["id"],
            action="totp_verify_failed",
            ip_address=ip,
        )
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    store.record_audit(user_id=user["id"], action="login_success", ip_address=ip)
    return _issue_session(
        response,
        request,
        settings,
        _login_response(settings, store, user, totp_setup_required=False),
    )


@router.get("/me", response_model=UserPublic)
def me(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    store: PlatformStore = Depends(get_platform_store),
) -> UserPublic:
    public = store.public_user(current.user)
    return UserPublic(**public)


@router.post("/totp/setup", response_model=TotpSetupResponse)
def totp_setup(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    store: PlatformStore = Depends(get_platform_store),
    settings: PlatformSettings = Depends(_settings),
) -> TotpSetupResponse:
    if current.user.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="TOTP is already enabled")
    secret = new_totp_secret()
    store.set_totp_secret(str(current.id), secret, enabled=False)
    issuer = settings.platform_totp_issuer
    uri = totp_provisioning_uri(
        secret=secret,
        email=str(current.user["email"]),
        issuer=issuer,
    )
    return TotpSetupResponse(provisioning_uri=uri, issuer=issuer)


@router.post("/totp/confirm", response_model=LoginResponse)
def totp_confirm(
    body: TotpConfirmRequest,
    request: Request,
    response: Response,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    store: PlatformStore = Depends(get_platform_store),
    settings: PlatformSettings = Depends(_settings),
) -> LoginResponse:
    secret = str(current.user.get("totp_secret") or "")
    if not secret:
        raise HTTPException(status_code=400, detail="Call /totp/setup first")
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    store.set_totp_secret(str(current.id), secret, enabled=True)
    refreshed = store.get_user_by_id(str(current.id))
    if refreshed is None:
        raise HTTPException(status_code=500, detail="User not found after TOTP confirm")
    store.record_audit(
        user_id=str(current.id),
        action="totp_enabled",
        ip_address=audit_request_ip(request, settings),
    )
    return _issue_session(
        response,
        request,
        settings,
        _login_response(settings, store, refreshed, totp_setup_required=False),
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    store: PlatformStore = Depends(get_platform_store),
    settings: PlatformSettings = Depends(_settings),
) -> dict[str, bool]:
    store.record_audit(
        user_id=str(current.id),
        action="logout",
        ip_address=audit_request_ip(request, settings),
    )
    clear_session_cookie(response, settings)
    return {"ok": True}


@router.get("/health")
def auth_health(
    settings: PlatformSettings = Depends(_settings),
) -> dict[str, str]:
    if not settings.platform_enabled:
        return {"status": "disabled"}
    return {"status": "ok"}
