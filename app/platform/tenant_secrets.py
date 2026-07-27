"""Per-tenant secret resolution from DB (encrypted) or environment."""

from __future__ import annotations

import os
import re
from typing import Any

from app.config import get_platform_settings
from app.platform.field_crypto import decrypt_field, encrypt_field

_SECRET_ENV_KEYS = {
    "xcockpit_api_key": "XCOCKPIT_API_KEY",
    "stellar_xdr_api_key": "STELLAR_XDR_API_KEY",
    "stellar_cases_api_key": "STELLAR_CASES_API_KEY",
}

_ENV_TO_CONFIG_KEY = {v: k for k, v in _SECRET_ENV_KEYS.items()}


def tenant_env_suffix(tenant_source_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", str(tenant_source_id or "").strip()).strip("_")
    return safe.upper() or "TENANT"


def tenant_env_var(tenant_source_id: str, base_name: str) -> str:
    return f"{base_name}__{tenant_env_suffix(tenant_source_id)}"


def read_tenant_env_secret(tenant_source_id: str, base_name: str) -> str:
    return str(os.environ.get(tenant_env_var(tenant_source_id, base_name), "") or "").strip()


def read_cycraft_secret(
    tenant_source_id: str,
    base_name: str,
    cycraft_config: dict[str, Any] | None,
) -> str:
    """Read tenant secret from encrypted DB config, else per-tenant env."""
    cfg_key = _ENV_TO_CONFIG_KEY.get(base_name)
    if cfg_key and cycraft_config:
        enc_map = cycraft_config.get("secrets_enc")
        if isinstance(enc_map, dict) and enc_map.get(cfg_key):
            ps = get_platform_settings()
            plain = decrypt_field(str(enc_map[cfg_key]), ps.platform_secret_key)
            if plain:
                return plain
    return read_tenant_env_secret(tenant_source_id, base_name)


def tenant_secret_configured(
    tenant_source_id: str,
    base_name: str,
    cycraft_config: dict[str, Any] | None = None,
) -> bool:
    return bool(read_cycraft_secret(tenant_source_id, base_name, cycraft_config))


def encrypt_cycraft_secrets(updates: dict[str, str]) -> dict[str, str]:
    """Encrypt plaintext secret fields for storage in config_json."""
    ps = get_platform_settings()
    key = ps.platform_secret_key
    out: dict[str, str] = {}
    for field, plain in updates.items():
        if field not in _SECRET_ENV_KEYS:
            continue
        value = str(plain or "").strip()
        if value:
            out[field] = encrypt_field(value, key)
    return out
