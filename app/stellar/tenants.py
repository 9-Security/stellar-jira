"""Load Stellar report tenants from config/stellar_tenants.json (multi-tenant)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import StellarSettings
from app.stellar.tenant_model import StellarTenant

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def tenants_file_nonempty(repo_root: Path, relative_path: str) -> bool:
    path = repo_root / relative_path
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(raw, list) and len(raw) > 0


def _settings_env_fallback(settings: StellarSettings, name: str) -> str | None:
    if name == "STELLAR_TENANT_ID":
        v = settings.stellar_tenant_id
        return str(v).strip() if v else None
    return None


def _expand_env_strings(obj: object, settings: StellarSettings | None = None) -> object:
    if isinstance(obj, str):

        def repl(m: re.Match[str]) -> str:
            name = m.group(1)
            v = os.environ.get(name)
            if v is None and settings is not None:
                v = _settings_env_fallback(settings, name)
            if v is None:
                raise ValueError(f"Environment variable {name!r} is not set (referenced in stellar_tenants.json)")
            return v

        return _ENV_REF.sub(repl, obj)
    if isinstance(obj, dict):
        return {str(k): _expand_env_strings(v, settings) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_strings(x, settings) for x in obj]
    return obj


def load_stellar_tenants(settings: StellarSettings, repo_root: Path) -> list[StellarTenant]:
    rel = getattr(settings, "stellar_tenants_path", None) or "config/stellar_tenants.json"
    path = repo_root / rel
    if not tenants_file_nonempty(repo_root, rel):
        return [_legacy_tenant_from_settings(settings)]

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return [_legacy_tenant_from_settings(settings)]
    expanded = _expand_env_strings(raw, settings)
    out: list[StellarTenant] = []
    seen: set[str] = set()
    for i, item in enumerate(expanded):
        if not isinstance(item, dict):
            raise ValueError(f"stellar_tenants.json: entry {i} must be an object")
        try:
            t = StellarTenant.model_validate(item)
        except ValidationError as e:
            raise ValueError(f"stellar_tenants.json entry {i}: {e}") from e
        if t.source_id in seen:
            raise ValueError(f"Duplicate source_id in stellar_tenants.json: {t.source_id!r}")
        seen.add(t.source_id)
        out.append(t)
    return out


def _legacy_tenant_from_settings(settings: StellarSettings) -> StellarTenant:
    cc = (settings.stellar_default_customer_code or "DEFAULT").strip().upper()
    if len(cc) < 2:
        cc = "DEFAULT"
    return StellarTenant(
        source_id=(settings.stellar_poll_source_id or "stellar").strip() or "stellar",
        customer_code=cc[:16],
        tenant_name=None,
        tenant_id=settings.stellar_tenant_id,
        products=["darktrace"],
        jira_project_key=settings.stellar_jira_project_key,
        report_title=settings.stellar_default_customer_code,
    )


def get_tenant_by_source_id(tenants: list[StellarTenant], source_id: str) -> StellarTenant | None:
    sid = source_id.strip()
    for t in tenants:
        if t.source_id == sid:
            return t
    return None


def get_tenant_by_id(tenants: list[StellarTenant], tenant_id: str) -> StellarTenant | None:
    needle = str(tenant_id or "").strip()
    if not needle:
        return None
    matches = [t for t in tenants if (t.tenant_id or "").strip() == needle]
    return matches[0] if len(matches) == 1 else None


def get_tenant_by_name(tenants: list[StellarTenant], tenant_name: str) -> StellarTenant | None:
    needle = str(tenant_name or "").strip().casefold()
    if not needle:
        return None
    matches = [
        t for t in tenants if (t.tenant_name or "").strip().casefold() == needle
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_case_tenant(
    tenants: list[StellarTenant],
    case: dict[str, Any],
) -> tuple[StellarTenant | None, str]:
    """Resolve a case to one registry entry without cross-tenant fallback.

    ``cust_id`` is authoritative. If the case includes an unknown ``cust_id`` we
    intentionally do not fall back to the mutable display name.
    """
    cust_id = str(case.get("cust_id") or "").strip()
    tenant_name = str(case.get("tenant_name") or "").strip()
    if cust_id:
        tenant = get_tenant_by_id(tenants, cust_id)
        if tenant is None:
            return None, "unknown_tenant_id"
        configured_name = str(tenant.tenant_name or "").strip()
        if configured_name and tenant_name and configured_name.casefold() != tenant_name.casefold():
            return None, "tenant_name_mismatch"
        return tenant, "tenant_id"
    tenant = get_tenant_by_name(tenants, tenant_name)
    if tenant is not None:
        return tenant, "tenant_name"
    return None, "missing_or_unknown_tenant"


def validate_tenant_registry(tenants: list[StellarTenant]) -> list[str]:
    errors: list[str] = []
    seen_ids: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    seen_codes: dict[str, str] = {}
    for tenant in tenants:
        tid = str(tenant.tenant_id or "").strip()
        name = str(tenant.tenant_name or "").strip().casefold()
        code = tenant.customer_code
        if not tid:
            errors.append(f"{tenant.source_id}: tenant_id is required for strict sync")
        elif tid in seen_ids:
            errors.append(
                f"{tenant.source_id}: duplicate tenant_id also used by {seen_ids[tid]}"
            )
        else:
            seen_ids[tid] = tenant.source_id
        if not name:
            errors.append(f"{tenant.source_id}: tenant_name is required for strict sync")
        elif name in seen_names:
            errors.append(
                f"{tenant.source_id}: duplicate tenant_name also used by {seen_names[name]}"
            )
        else:
            seen_names[name] = tenant.source_id
        if code in seen_codes:
            errors.append(
                f"{tenant.source_id}: duplicate customer_code also used by {seen_codes[code]}"
            )
        else:
            seen_codes[code] = tenant.source_id
    return errors


def resolve_report_tenant(
    tenants: list[StellarTenant],
    *,
    source_id: str | None = None,
    tenant_id: str | None = None,
    tenant_name: str | None = None,
    customer_code: str | None = None,
) -> StellarTenant:
    """Pick tenant for a report run. With multiple configured tenants, ``source_id`` is required."""
    keys = [k for k, v in (
        ("source_id", source_id),
        ("tenant_id", tenant_id),
        ("tenant_name", tenant_name),
        ("customer_code", customer_code),
    ) if v and str(v).strip()]

    if len(keys) > 1:
        raise ValueError(f"Specify only one of: source_id, tenant_id, tenant_name, customer_code (got {keys})")

    if source_id and str(source_id).strip():
        t = get_tenant_by_source_id(tenants, source_id)
        if t is None:
            known = ", ".join(sorted(x.source_id for x in tenants))
            raise ValueError(f"Unknown tenant source_id={source_id!r}. Configured: {known or '(none)'}")
        return t

    if tenant_id and str(tenant_id).strip():
        needle = str(tenant_id).strip()
        for t in tenants:
            if (t.tenant_id or "").strip() == needle:
                return t
        raise ValueError(f"No tenant with tenant_id={needle!r}")

    if tenant_name and str(tenant_name).strip():
        needle = str(tenant_name).strip().lower()
        matches = [t for t in tenants if (t.tenant_name or "").strip().lower() == needle]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Multiple tenants match tenant_name={tenant_name!r}; use --tenant source_id")
        raise ValueError(f"No tenant with tenant_name={tenant_name!r}")

    if customer_code and str(customer_code).strip():
        needle = str(customer_code).strip().upper()
        matches = [t for t in tenants if t.customer_code == needle]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Multiple tenants match customer_code={customer_code!r}; use --tenant source_id")
        raise ValueError(f"No tenant with customer_code={customer_code!r}")

    if len(tenants) == 1:
        return tenants[0]
    known = ", ".join(sorted(t.source_id for t in tenants))
    raise ValueError(
        f"Multiple Stellar tenants configured; specify --tenant <source_id>. Configured: {known}"
    )
