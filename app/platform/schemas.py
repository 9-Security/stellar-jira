"""Pydantic models for platform auth API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    requires_totp: bool = False
    login_token: str | None = None
    totp_setup_required: bool = False
    user: dict | None = None


class TotpVerifyRequest(BaseModel):
    login_token: str = Field(min_length=10)
    code: str = Field(min_length=6, max_length=16)


class TotpSetupResponse(BaseModel):
    provisioning_uri: str
    issuer: str


class TotpConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class UserPublic(BaseModel):
    id: str
    email: str
    role: str
    tenant_source_id: str | None = None
    totp_enabled: bool
    totp_policy: str = "optional"
    is_active: bool
    created_at: str | None = None
