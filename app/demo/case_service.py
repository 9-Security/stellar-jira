"""Read-only case queries for Demo dashboard (real sync data)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import StellarSettings
from app.demo.case_number import enrich_case_row, load_case_number_index, resolve_case_lookup_key
from app.demo.overview_query import OverviewQuery
from app.dates import format_detection_time
from app.stellar.case_assets import extract_affected_hosts
from app.stellar.case_display_name import stellar_case_display_name
from app.stellar.jira_draft import stellar_case_detail_lines
from app.sync.case_snapshots import CaseSnapshotStore
from app.sync.state import PENDING_JIRA_KEY

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERMINAL_STATUSES = frozenset({"resolved", "closed", "cancelled", "done"})
_RECENT_CASES_LIMIT = 50


def sync_db_path(st: StellarSettings) -> Path:
    path = Path(st.stellar_sync_state_db)
    return path if path.is_absolute() else _REPO_ROOT / path


def _source_id(st: StellarSettings) -> str:
    return str(st.stellar_poll_source_id or "stellar").strip() or "stellar"


def _is_open_status(status: str | None) -> bool:
    return str(status or "").strip().lower() not in _TERMINAL_STATUSES


def _parse_synced_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _case_row(
    link: dict[str, Any],
    snapshot: dict[str, Any] | None,
    bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    case = {}
    if isinstance(bundle, dict):
        raw_case = bundle.get("case")
        if isinstance(raw_case, dict):
            case = raw_case
    severity = (
        str(snapshot.get("severity") or case.get("severity") or "").strip()
        if snapshot
        else str(case.get("severity") or "").strip()
    )
    status = str(case.get("status") or "").strip()
    title = stellar_case_display_name(case, bundle) if case or bundle else ""
    modified_ms = int(
        (snapshot or {}).get("modified_at_ms")
        or case.get("modified_at")
        or 0
    )
    return {
        "stellar_case_id": link.get("incident_id"),
        "jira_key": link.get("jira_key"),
        "tenant_source_id": link.get("tenant_source_id"),
        "tenant_name": link.get("tenant_name"),
        "customer_code": link.get("customer_code"),
        "title": title,
        "severity": severity or None,
        "status": status or None,
        "is_open": _is_open_status(status),
        "synced_at": link.get("synced_at"),
        "modified_at_ms": modified_ms or None,
        "detected_at": format_detection_time(
            case.get("created_at"),
            timezone_name="Asia/Taipei",
        )
        if case
        else None,
    }


def _list_links(
    st: StellarSettings,
    *,
    tenant_source_id: str | None = None,
) -> list[dict[str, Any]]:
    path = sync_db_path(st)
    if not path.is_file():
        return []
    source_id = _source_id(st)
    clauses = ["source_id=?", "jira_key!=?"]
    params: list[Any] = [source_id, PENDING_JIRA_KEY]
    if tenant_source_id:
        clauses.append("tenant_source_id=?")
        params.append(tenant_source_id)
    where = " AND ".join(clauses)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            f"SELECT incident_id, jira_key, synced_at, tenant_source_id, tenant_id, "
            f"tenant_name, customer_code FROM incident_jira WHERE {where} "
            "ORDER BY synced_at DESC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def _load_bundle(
    path: Path,
    source_id: str,
    incident_id: str,
    *,
    light: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    store = CaseSnapshotStore(path)
    snapshot = store.get_latest(source_id, incident_id)
    if snapshot is None:
        return None, None
    if not light:
        bundle = store.load_bundle_payload(snapshot)
        if not isinstance(bundle, dict):
            return snapshot, None
        return snapshot, bundle

    bundle: dict[str, Any] = {}
    raw_case = snapshot.get("case_json")
    if isinstance(raw_case, str) and raw_case.strip():
        try:
            parsed = json.loads(raw_case)
            if isinstance(parsed, dict):
                bundle["case"] = parsed
        except json.JSONDecodeError:
            pass
    if not bundle.get("case") and snapshot.get("storage_mode") == "file":
        full = store.load_bundle_payload(snapshot)
        if isinstance(full, dict):
            bundle = full
    return snapshot, bundle or None


def _case_timestamp_ms(
    snapshot: dict[str, Any] | None,
    bundle: dict[str, Any] | None,
    field: str,
) -> int:
    case = bundle.get("case") if isinstance(bundle, dict) else {}
    if not isinstance(case, dict):
        case = {}
    if field == "created_at":
        return int(case.get("created_at") or 0)
    return int((snapshot or {}).get("modified_at_ms") or case.get("modified_at") or 0)


def build_overview(
    st: StellarSettings,
    *,
    tenant_source_id: str | None = None,
    query: OverviewQuery | None = None,
) -> dict[str, Any]:
    path = sync_db_path(st)
    source_id = _source_id(st)
    links = _list_links(st, tenant_source_id=tenant_source_id)
    number_index = load_case_number_index(path, source_id)
    now = datetime.now(timezone.utc)
    oq = query or OverviewQuery(
        window="all",
        scope="modified",
        new_basis="created",
        since_ms=None,
        since_iso=None,
    )

    total = 0
    open_count = 0
    critical_high = 0
    new_in_window = 0
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_tenant: dict[str, int] = {}
    recent: list[dict[str, Any]] = []

    for link in links:
        incident_id = str(link.get("incident_id") or "")
        snapshot, bundle = _load_bundle(path, source_id, incident_id, light=True)
        scope_ms = _case_timestamp_ms(snapshot, bundle, oq.scope_field)
        if oq.since_ms is not None and scope_ms < oq.since_ms:
            continue
        row = enrich_case_row(_case_row(link, snapshot, bundle), number_index)
        total += 1
        if row.get("is_open"):
            open_count += 1
        sev = str(row.get("severity") or "Unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if sev in {"Critical", "High"} and row.get("is_open"):
            critical_high += 1
        status = str(row.get("status") or "Unknown")
        by_status[status] = by_status.get(status, 0) + 1
        tenant_key = str(row.get("tenant_source_id") or row.get("tenant_name") or "unknown")
        by_tenant[tenant_key] = by_tenant.get(tenant_key, 0) + 1
        basis_ms = _case_timestamp_ms(snapshot, bundle, oq.new_basis_field)
        if oq.since_ms is None or basis_ms >= oq.since_ms:
            new_in_window += 1
        if len(recent) < _RECENT_CASES_LIMIT:
            recent.append(row)

    return {
        "summary": {
            "total_cases": total,
            "open_cases": open_count,
            "critical_high_open": critical_high,
            "new_in_window": new_in_window,
        },
        "by_severity": by_severity,
        "by_status": by_status,
        "by_tenant": by_tenant,
        "recent_cases": recent,
        "meta": {
            "source": "sync_db",
            "window": oq.window,
            "scope": oq.scope,
            "new_basis": oq.new_basis,
            "since": oq.since_iso,
            "as_of": now.isoformat(),
            "truncated": False,
        },
    }


def list_cases(
    st: StellarSettings,
    *,
    tenant_source_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    path = sync_db_path(st)
    source_id = _source_id(st)
    links = _list_links(st, tenant_source_id=tenant_source_id)
    number_index = load_case_number_index(path, source_id)
    rows: list[dict[str, Any]] = []
    for link in links:
        incident_id = str(link.get("incident_id") or "")
        snapshot, bundle = _load_bundle(path, source_id, incident_id, light=True)
        row = enrich_case_row(_case_row(link, snapshot, bundle), number_index)
        if severity and str(row.get("severity") or "").lower() != severity.strip().lower():
            continue
        if status and str(row.get("status") or "").lower() != status.strip().lower():
            continue
        if q:
            needle = q.strip().lower()
            hay = " ".join(
                str(row.get(k) or "")
                for k in (
                    "title",
                    "case_number",
                    "middleware_case_id",
                    "jira_key",
                    "stellar_case_id",
                    "tenant_name",
                    "customer_code",
                )
            ).lower()
            if needle not in hay:
                continue
        rows.append(row)

    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "data": page,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < total else None,
        },
    }


def get_case_detail(
    st: StellarSettings,
    case_id: str,
    *,
    tenant_source_id: str | None = None,
) -> dict[str, Any]:
    path = sync_db_path(st)
    source_id = _source_id(st)
    key = resolve_case_lookup_key(
        case_id,
        path=path,
        source_id=source_id,
    )
    if not key:
        raise ValueError("case id required")

    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT incident_id, jira_key, synced_at, tenant_source_id, tenant_id, "
            "tenant_name, customer_code FROM incident_jira "
            "WHERE source_id=? AND jira_key!=? AND (incident_id=? OR UPPER(jira_key)=?) "
            "LIMIT 1",
            (source_id, PENDING_JIRA_KEY, key, key.upper()),
        ).fetchone()
    if row is None:
        raise LookupError(f"case not found: {case_id}")
    link = dict(row)
    if tenant_source_id and str(link.get("tenant_source_id") or "") != tenant_source_id:
        raise PermissionError("tenant access denied")

    incident_id = str(link["incident_id"])
    snapshot, bundle = _load_bundle(path, source_id, incident_id)
    if bundle is None:
        raise LookupError(f"no snapshot for case: {case_id}")
    number_index = load_case_number_index(path, source_id)

    case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
    summary_lines = stellar_case_detail_lines(case, bundle)
    case_row = enrich_case_row(_case_row(link, snapshot, bundle), number_index)
    return {
        "case": case_row,
        "affected_hosts": extract_affected_hosts(bundle, limit=20),
        "summary_lines": summary_lines,
        "summary_text": "\n".join(summary_lines),
    }
