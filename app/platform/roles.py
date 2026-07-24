"""RBAC role definitions (PRD v0.1 §3)."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    SOC_ANALYST = "soc_analyst"
    SOC_VIEWER = "soc_viewer"
    TENANT_ADMIN = "tenant_admin"
    TENANT_VIEWER = "tenant_viewer"


PLATFORM_ROLES = frozenset(
    {
        UserRole.PLATFORM_ADMIN,
        UserRole.SOC_ANALYST,
        UserRole.SOC_VIEWER,
    }
)

TENANT_ROLES = frozenset(
    {
        UserRole.TENANT_ADMIN,
        UserRole.TENANT_VIEWER,
    }
)

TOTP_REQUIRED_ROLES = frozenset(
    {
        UserRole.PLATFORM_ADMIN,
        UserRole.SOC_ANALYST,
        UserRole.TENANT_ADMIN,
        UserRole.TENANT_VIEWER,
    }
)


def is_platform_role(role: str | UserRole) -> bool:
    try:
        return UserRole(str(role)) in PLATFORM_ROLES
    except ValueError:
        return False


def is_tenant_role(role: str | UserRole) -> bool:
    try:
        return UserRole(str(role)) in TENANT_ROLES
    except ValueError:
        return False


def role_requires_totp(role: str | UserRole, *, platform_require_totp: bool = True) -> bool:
    if not platform_require_totp:
        return False
    try:
        return UserRole(str(role)) in TOTP_REQUIRED_ROLES
    except ValueError:
        return False
