"""Admin user management API (Demo MVP)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.platform.deps import (
    CurrentUser,
    audit_request_ip,
    get_platform_store,
    require_roles,
)
from app.platform.roles import UserRole
from app.platform.security import hash_password
from app.platform.store import PlatformStore
from app.platform.totp_policy import VALID_TOTP_POLICIES

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_admin = require_roles(UserRole.PLATFORM_ADMIN)


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default=UserRole.SOC_ANALYST.value)
    tenant_source_id: str | None = None
    totp_policy: str = Field(default="optional")


class AdminUserPatch(BaseModel):
    role: str | None = None
    tenant_source_id: str | None = None
    totp_policy: str | None = None
    is_active: bool | None = None


@router.get("/users")
def list_users(
    current: Annotated[CurrentUser, Depends(_admin)],
    store: PlatformStore = Depends(get_platform_store),
    include_inactive: bool = False,
) -> dict[str, Any]:
    users = store.list_users(include_inactive=include_inactive)
    return {"data": [store.public_user(u) for u in users]}


@router.post("/users")
def create_user(
    body: AdminUserCreate,
    request: Request,
    current: Annotated[CurrentUser, Depends(_admin)],
    store: PlatformStore = Depends(get_platform_store),
) -> dict[str, Any]:
    if body.totp_policy not in VALID_TOTP_POLICIES:
        raise HTTPException(status_code=400, detail="invalid totp_policy")
    try:
        user = store.create_user(
            email=body.email,
            password_hash=hash_password(body.password),
            role=body.role,
            tenant_source_id=body.tenant_source_id,
            totp_policy=body.totp_policy,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    store.record_audit(
        user_id=current.id,
        action="user_created",
        resource_type="user",
        resource_id=user["id"],
        ip_address=audit_request_ip(request),
        detail={"email": user["email"], "role": user["role"]},
    )
    return {"data": store.public_user(user)}


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    body: AdminUserPatch,
    request: Request,
    current: Annotated[CurrentUser, Depends(_admin)],
    store: PlatformStore = Depends(get_platform_store),
) -> dict[str, Any]:
    if user_id == current.id and body.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    if body.is_active is False or (
        body.role is not None and body.role != UserRole.PLATFORM_ADMIN.value
    ):
        target = store.get_user_by_id(user_id)
        if target and str(target.get("role") or "") == UserRole.PLATFORM_ADMIN.value:
            admins = [
                u
                for u in store.list_users(include_inactive=False)
                if str(u.get("role") or "") == UserRole.PLATFORM_ADMIN.value
            ]
            if len(admins) <= 1 and str(target["id"]) == str(admins[0]["id"]):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove or deactivate the last platform admin",
                )
    if body.totp_policy is not None and body.totp_policy not in VALID_TOTP_POLICIES:
        raise HTTPException(status_code=400, detail="invalid totp_policy")
    try:
        user = store.update_user(
            user_id,
            role=body.role,
            tenant_source_id=body.tenant_source_id,
            totp_policy=body.totp_policy,
            is_active=body.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    store.record_audit(
        user_id=current.id,
        action="user_updated",
        resource_type="user",
        resource_id=user_id,
        ip_address=audit_request_ip(request),
        detail=body.model_dump(exclude_none=True),
    )
    return {"data": store.public_user(user)}


@router.post("/users/{user_id}/totp-reset")
def reset_user_totp(
    user_id: str,
    request: Request,
    current: Annotated[CurrentUser, Depends(_admin)],
    store: PlatformStore = Depends(get_platform_store),
) -> dict[str, Any]:
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    store.clear_totp(user_id)
    refreshed = store.get_user_by_id(user_id)
    assert refreshed is not None
    store.record_audit(
        user_id=current.id,
        action="user_totp_reset",
        resource_type="user",
        resource_id=user_id,
        ip_address=audit_request_ip(request),
    )
    return {"data": store.public_user(refreshed)}
