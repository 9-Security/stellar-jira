"""Per-user TOTP policy (Demo MVP v0.2)."""

from __future__ import annotations

from typing import Any, Literal

TotpPolicy = Literal["off", "optional", "required"]

VALID_TOTP_POLICIES = frozenset({"off", "optional", "required"})


def normalize_totp_policy(value: str | None) -> TotpPolicy:
    raw = str(value or "optional").strip().lower()
    if raw in VALID_TOTP_POLICIES:
        return raw  # type: ignore[return-value]
    return "optional"


def login_requires_totp_verify(user: dict[str, Any]) -> bool:
    """Password OK → need second step with TOTP code."""
    policy = normalize_totp_policy(user.get("totp_policy"))
    if policy == "off":
        return False
    if policy == "optional":
        return bool(user.get("totp_enabled"))
    # required: only verify when already bound
    return bool(user.get("totp_enabled"))


def login_requires_totp_setup(user: dict[str, Any]) -> bool:
    """Password OK → issue limited token until TOTP is configured."""
    policy = normalize_totp_policy(user.get("totp_policy"))
    if policy == "required" and not user.get("totp_enabled"):
        return True
    return False


def session_requires_totp_setup(user: dict[str, Any]) -> bool:
    return login_requires_totp_setup(user)


def session_blocks_without_totp(user: dict[str, Any]) -> bool:
    """Full API access requires TOTP when policy is required and enabled check."""
    policy = normalize_totp_policy(user.get("totp_policy"))
    if policy == "required" and not user.get("totp_enabled"):
        return True
    return False
