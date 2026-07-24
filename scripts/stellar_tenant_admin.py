#!/usr/bin/env python3
"""Manage the Stellar multi-tenant registry and runtime health."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.stellar.client import StellarClient  # noqa: E402
from app.stellar.tenants import (  # noqa: E402
    load_stellar_tenants,
    validate_tenant_registry,
)
from app.sync.state import SyncState  # noqa: E402


def _config_path() -> Path:
    st = get_stellar_settings()
    return ROOT / (st.stellar_tenants_path or "config/stellar_tenants.json")


def _raw_registry() -> list[dict[str, Any]]:
    path = _config_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON array")
    return [dict(x) for x in raw if isinstance(x, dict)]


def _write_registry(rows: list[dict[str, Any]]) -> None:
    path = _config_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _slug(name: str) -> str:
    import re

    value = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return value[:64] or "tenant"


async def _api_tenants() -> list[dict[str, Any]]:
    st = get_stellar_settings()
    async with StellarClient(
        base_url=str(st.stellar_base_url).rstrip("/"),
        api_key=st.stellar_api_key or "",
        timeout_seconds=st.stellar_timeout_seconds,
        verify_tls=st.stellar_tls_verify,
        tenant_id=None,
        http_max_retries=st.stellar_http_max_retries,
    ) as client:
        raw = await client._request("GET", "tenants")
    data = raw.get("data") if isinstance(raw, dict) else raw
    if isinstance(data, dict):
        data = data.get("docs") or data.get("tenants") or []
    return [dict(x) for x in data or [] if isinstance(x, dict)]


def _config_summary() -> list[dict[str, Any]]:
    st = get_stellar_settings()
    tenants = load_stellar_tenants(st, ROOT)
    state = SyncState(ROOT / st.stellar_sync_state_db)
    state.init(legacy_source_id=st.stellar_poll_source_id or "stellar")
    links = state.tenant_link_counts()
    quarantine = state.list_quarantined_cases(st.stellar_poll_source_id or "stellar")
    qcounts: dict[str, int] = {}
    for row in quarantine:
        key = str(row.get("tenant_name") or row.get("tenant_id") or "(unknown)")
        qcounts[key] = qcounts.get(key, 0) + 1
    out: list[dict[str, Any]] = []
    for tenant in tenants:
        stats_raw = state.get_meta(f"last_tenant_stats:{tenant.source_id}")
        try:
            stats = json.loads(stats_raw) if stats_raw else {}
        except json.JSONDecodeError:
            stats = {}
        out.append(
            {
                "source_id": tenant.source_id,
                "tenant_name": tenant.tenant_name,
                "tenant_id": tenant.tenant_id,
                "customer_code": tenant.customer_code,
                "enabled": tenant.enabled,
                "sync_enabled": tenant.sync_enabled,
                "reporting_enabled": tenant.reporting_enabled,
                "jira_project_key": tenant.jira_project_key or st.stellar_jira_project_key,
                "linked_tickets": links.get(tenant.source_id, 0),
                "quarantined": qcounts.get(str(tenant.tenant_name or ""), 0),
                "last_cycle": stats,
            }
        )
    return out


async def cmd_discover(apply: bool) -> int:
    api_rows = await _api_tenants()
    current = _raw_registry()
    configured = load_stellar_tenants(get_stellar_settings(), ROOT)
    known_ids = {
        str(tenant.tenant_id or "").strip(): tenant
        for tenant in configured
        if str(tenant.tenant_id or "").strip()
    }
    discovered: list[dict[str, Any]] = []
    for row in api_rows:
        tenant_id = str(
            row.get("cust_id") or row.get("tenant_id") or row.get("id") or ""
        ).strip()
        tenant_name = str(
            row.get("cust_name") or row.get("tenant_name") or row.get("name") or ""
        ).strip()
        exists = known_ids.get(tenant_id)
        discovered.append(
            {
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "configured": bool(exists),
                "source_id": exists.source_id if exists else None,
                "ds_num": row.get("ds_num"),
                "user_num": row.get("user_num"),
            }
        )
        if apply and tenant_id and not exists:
            source_id = _slug(tenant_name)
            used = {str(x.get("source_id") or "") for x in current}
            base = source_id
            n = 2
            while source_id in used:
                source_id = f"{base}-{n}"
                n += 1
            current.append(
                {
                    "source_id": source_id,
                    "enabled": False,
                    "sync_enabled": False,
                    "reporting_enabled": False,
                    "customer_code": _slug(tenant_name).replace("-", "").upper()[:16]
                    or "TENANT",
                    "tenant_name": tenant_name,
                    "tenant_id": tenant_id,
                    "products": ["darktrace", "cortex"],
                    "jira_project_key": get_stellar_settings().stellar_jira_project_key,
                    "report_title": tenant_name,
                }
            )
    if apply:
        _write_registry(current)
    print(
        json.dumps(
            {"ok": True, "applied": apply, "tenants": discovered},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def cmd_validate() -> int:
    st = get_stellar_settings()
    tenants = load_stellar_tenants(st, ROOT)
    errors = validate_tenant_registry(tenants)
    api_rows = await _api_tenants()
    api_by_id = {
        str(x.get("cust_id") or x.get("tenant_id") or x.get("id") or "").strip(): x
        for x in api_rows
    }
    checks: list[dict[str, Any]] = []
    for tenant in tenants:
        api = api_by_id.get(str(tenant.tenant_id or "").strip())
        check = {
            "source_id": tenant.source_id,
            "tenant_name": tenant.tenant_name,
            "tenant_id": tenant.tenant_id,
            "visible_in_api": api is not None,
            "api_name": (
                api.get("cust_name") or api.get("tenant_name") or api.get("name")
                if api
                else None
            ),
            "ds_num": api.get("ds_num") if api else None,
        }
        if api is None:
            errors.append(f"{tenant.source_id}: tenant_id not visible in GET /tenants")
        elif str(check["api_name"] or "").casefold() != str(tenant.tenant_name or "").casefold():
            errors.append(
                f"{tenant.source_id}: API name {check['api_name']!r} != configured "
                f"{tenant.tenant_name!r}"
            )
        checks.append(check)
    print(
        json.dumps(
            {"ok": not errors, "errors": errors, "checks": checks},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


def cmd_toggle(source_id: str, enabled: bool) -> int:
    rows = _raw_registry()
    found = False
    for row in rows:
        if str(row.get("source_id") or "") == source_id:
            row["enabled"] = enabled
            row["sync_enabled"] = enabled
            row["reporting_enabled"] = enabled
            found = True
            break
    if not found:
        print(json.dumps({"ok": False, "error": f"unknown source_id={source_id}"}))
        return 1
    _write_registry(rows)
    print(json.dumps({"ok": True, "source_id": source_id, "enabled": enabled}))
    return 0


def cmd_quarantine() -> int:
    st = get_stellar_settings()
    state = SyncState(ROOT / st.stellar_sync_state_db)
    state.init(legacy_source_id=st.stellar_poll_source_id or "stellar")
    rows = state.list_quarantined_cases(st.stellar_poll_source_id or "stellar")
    for row in rows:
        row.pop("case", None)
    print(json.dumps({"ok": True, "count": len(rows), "rows": rows}, ensure_ascii=False, indent=2))
    return 0


def cmd_backfill(apply: bool, assume_source_id: str | None) -> int:
    st = get_stellar_settings()
    db_path = ROOT / st.stellar_sync_state_db
    state = SyncState(db_path)
    state.init(legacy_source_id=st.stellar_poll_source_id or "stellar")
    tenants = load_stellar_tenants(st, ROOT)
    by_code = {tenant.customer_code.casefold(): tenant for tenant in tenants}
    assumed = next(
        (tenant for tenant in tenants if tenant.source_id == assume_source_id),
        None,
    )
    if assume_source_id and assumed is None:
        print(json.dumps({"ok": False, "error": f"unknown source_id={assume_source_id}"}))
        return 1
    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT i.source_id, i.incident_id, i.jira_key, s.customer_code "
            "FROM incident_jira i LEFT JOIN stellar_case_snapshots s ON "
            "s.snapshot_id=(SELECT s2.snapshot_id FROM stellar_case_snapshots s2 "
            "WHERE s2.source_id=i.source_id AND s2.stellar_case_id=i.incident_id "
            "ORDER BY s2.modified_at_ms DESC, s2.captured_at DESC LIMIT 1) "
            "WHERE i.tenant_source_id IS NULL OR i.tenant_source_id=''"
        ).fetchall()
    plans: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["customer_code"] or "").strip()
        tenant = by_code.get(code.casefold())
        matched_by = "snapshot_customer_code"
        if tenant is None and assumed is not None:
            tenant = assumed
            matched_by = "operator_assumption"
        plan = {
            "source_id": row["source_id"],
            "case_id": row["incident_id"],
            "jira_key": row["jira_key"],
            "snapshot_customer_code": code,
            "tenant_source_id": tenant.source_id if tenant else None,
            "matched_by": matched_by if tenant else None,
        }
        plans.append(plan)
        if apply and tenant is not None:
            state.update_incident_tenant(
                str(row["source_id"]),
                str(row["incident_id"]),
                tenant_source_id=tenant.source_id,
                tenant_id=str(tenant.tenant_id or ""),
                tenant_name=str(tenant.tenant_name or ""),
                customer_code=tenant.customer_code,
            )
    unresolved = sum(1 for plan in plans if not plan["tenant_source_id"])
    print(
        json.dumps(
            {
                "ok": True,
                "complete": unresolved == 0,
                "applied": apply,
                "matched": len(plans) - unresolved,
                "unresolved": unresolved,
                "plans": plans,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Stellar tenant registry management")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    discover = sub.add_parser("discover")
    discover.add_argument("--apply", action="store_true")
    sub.add_parser("validate")
    sub.add_parser("health")
    sub.add_parser("quarantine")
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--apply", action="store_true")
    backfill.add_argument(
        "--assume",
        metavar="SOURCE_ID",
        help="Assign rows with no snapshot metadata to this tenant (explicit migration)",
    )
    enable = sub.add_parser("enable")
    enable.add_argument("source_id")
    disable = sub.add_parser("disable")
    disable.add_argument("source_id")
    args = parser.parse_args()

    get_stellar_settings.cache_clear()
    if args.command in {"list", "health"}:
        print(json.dumps({"ok": True, "tenants": _config_summary()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "discover":
        return await cmd_discover(args.apply)
    if args.command == "validate":
        return await cmd_validate()
    if args.command == "quarantine":
        return cmd_quarantine()
    if args.command == "backfill":
        return cmd_backfill(args.apply, args.assume)
    if args.command == "enable":
        return cmd_toggle(args.source_id, True)
    if args.command == "disable":
        return cmd_toggle(args.source_id, False)
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
