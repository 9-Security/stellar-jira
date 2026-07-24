"""Password hashing, JWT, and TOTP helpers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import bcrypt
import jwt
import pyotp

from app.config import PlatformSettings


def hash_password(password: str) -> str:
    raw = str(password or "").encode("utf-8")
    if len(raw) < 8:
        raise ValueError("password must be at least 8 characters")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            str(password or "").encode("utf-8"),
            str(password_hash or "").encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    settings: PlatformSettings,
    *,
    user_id: str,
    role: str,
    tenant_source_id: str | None,
    totp_setup_required: bool = False,
) -> str:
    ttl = timedelta(hours=int(settings.platform_session_ttl_hours))
    now = _now_utc()
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_source_id": tenant_source_id,
        "typ": "access",
        "totp_setup_required": totp_setup_required,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, settings.platform_secret_key, algorithm="HS256")


def create_login_token(settings: PlatformSettings, *, user_id: str) -> str:
    ttl = timedelta(minutes=int(settings.platform_login_token_ttl_minutes))
    now = _now_utc()
    payload = {
        "sub": user_id,
        "typ": "login",
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, settings.platform_secret_key, algorithm="HS256")


def decode_token(settings: PlatformSettings, token: str, *, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.platform_secret_key,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError as e:
        raise ValueError("invalid or expired token") from e
    if str(payload.get("typ") or "") != expected_type:
        raise ValueError("invalid token type")
    return payload


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(
    *,
    secret: str,
    email: str,
    issuer: str,
) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def verify_totp_code(secret: str, code: str) -> bool:
    normalized = str(code or "").strip().replace(" ", "")
    if not normalized.isdigit() or len(normalized) != 6:
        return False
    totp = pyotp.TOTP(str(secret or "").strip())
    return bool(totp.verify(normalized, valid_window=1))


def generate_backup_codes(count: int = 8) -> list[str]:
    return [secrets.token_hex(4).upper() for _ in range(max(1, count))]
