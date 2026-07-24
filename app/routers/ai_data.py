"""Read-only API for locally archived Stellar cases and alerts."""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import StellarSettings, get_stellar_settings
from app.sync.case_snapshots import CaseSnapshotStore
from app.sync.state import PENDING_JIRA_KEY

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECTIONS = frozenset({"case", "alerts", "observables", "summary", "activities", "ai_summary"})

router = APIRouter(prefix="/v1/ai-data", tags=["ai-data"])


def _settings() -> StellarSettings:
    get_stellar_settings.cache_clear()
    return get_stellar_settings()


def _db_path(st: StellarSettings) -> Path:
    path = Path(st.stellar_sync_state_db)
    return path if path.is_absolute() else _REPO_ROOT / path


def _require_read_access(
    st: StellarSettings,
    authorization: str | None,
    x_ai_data_token: str | None,
) -> None:
    configured = str(st.ai_data_api_token or "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="AI_DATA_API_TOKEN is not configured",
        )
    bearer = ""
    raw_authorization = str(authorization or "").strip()
    if raw_authorization.lower().startswith("bearer "):
        bearer = raw_authorization[7:].strip()
    presented = bearer or str(x_ai_data_token or "").strip()
    if not presented or not secrets.compare_digest(presented, configured):
        raise HTTPException(status_code=403, detail="Invalid or missing AI data token")


def _connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Sync state database does not exist")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    return db


def _latest_case(
    st: StellarSettings,
    jira_key: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    key = str(jira_key or "").strip().upper()
    source_id = str(st.stellar_poll_source_id or "stellar").strip() or "stellar"
    path = _db_path(st)
    with _connection(path) as db:
        link = db.execute(
            "SELECT source_id, incident_id, jira_key, synced_at, tenant_source_id, "
            "tenant_id, tenant_name, customer_code FROM incident_jira "
            "WHERE source_id=? AND UPPER(jira_key)=? AND jira_key!=? LIMIT 1",
            (source_id, key, PENDING_JIRA_KEY),
        ).fetchone()
    if link is None:
        raise HTTPException(status_code=404, detail=f"Case not found for Jira key {key}")
    link_data = dict(link)
    store = CaseSnapshotStore(path)
    snapshot = store.get_latest(source_id, str(link_data["incident_id"]))
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No snapshot found for Jira key {key}")
    bundle = store.load_bundle_payload(snapshot)
    if not isinstance(bundle, dict):
        raise HTTPException(status_code=500, detail="Stored case snapshot is invalid")
    return link_data, snapshot, bundle


def _alert_docs(alerts_payload: Any) -> list[Any]:
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        return data["docs"]
    return data if isinstance(data, list) else []


@router.get("/cases")
def list_cases(
    tenant: str = Query(default="", max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_ai_data_token: str | None = Header(default=None, alias="X-AI-Data-Token"),
) -> dict[str, Any]:
    st = _settings()
    _require_read_access(st, authorization, x_ai_data_token)
    source_id = str(st.stellar_poll_source_id or "stellar").strip() or "stellar"
    path = _db_path(st)
    tenant_filter = str(tenant or "").strip()
    where = "source_id=? AND jira_key!=?"
    params: list[Any] = [source_id, PENDING_JIRA_KEY]
    if tenant_filter:
        where += " AND tenant_source_id=?"
        params.append(tenant_filter)
    with _connection(path) as db:
        total = int(
            db.execute(f"SELECT COUNT(*) FROM incident_jira WHERE {where}", params).fetchone()[0]
        )
        links = db.execute(
            "SELECT incident_id, jira_key, synced_at, tenant_source_id, tenant_id, "
            f"tenant_name, customer_code FROM incident_jira WHERE {where} "
            "ORDER BY synced_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()

    store = CaseSnapshotStore(path)
    rows: list[dict[str, Any]] = []
    for link in links:
        item = dict(link)
        snapshot = store.get_latest(source_id, str(item["incident_id"]))
        item["stellar_case_id"] = item.pop("incident_id")
        if snapshot is not None:
            item["snapshot"] = {
                "snapshot_id": snapshot.get("snapshot_id"),
                "modified_at_ms": snapshot.get("modified_at_ms"),
                "captured_at": snapshot.get("captured_at"),
                "severity": snapshot.get("severity"),
                "storage_mode": snapshot.get("storage_mode"),
                "bytes_size": snapshot.get("bytes_size"),
            }
        else:
            item["snapshot"] = None
        rows.append(item)
    return {
        "data": rows,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < total else None,
        },
    }


@router.get("/cases/{jira_key}")
def get_case(
    jira_key: str,
    include: str = Query(default="case,observables,summary,activities,ai_summary"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_ai_data_token: str | None = Header(default=None, alias="X-AI-Data-Token"),
) -> dict[str, Any]:
    st = _settings()
    _require_read_access(st, authorization, x_ai_data_token)
    requested = {part.strip() for part in str(include or "").split(",") if part.strip()}
    invalid = requested - _SECTIONS
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown include sections: {sorted(invalid)}")
    link, snapshot, bundle = _latest_case(st, jira_key)
    data: dict[str, Any] = {
        "jira_key": link["jira_key"],
        "stellar_case_id": link["incident_id"],
        "tenant_source_id": link.get("tenant_source_id"),
        "tenant_name": link.get("tenant_name"),
        "customer_code": link.get("customer_code"),
        "snapshot": {
            "snapshot_id": snapshot.get("snapshot_id"),
            "modified_at_ms": snapshot.get("modified_at_ms"),
            "captured_at": snapshot.get("captured_at"),
            "storage_mode": snapshot.get("storage_mode"),
            "bytes_size": snapshot.get("bytes_size"),
        },
    }
    for section in _SECTIONS:
        if section in requested:
            data[section] = bundle.get(section)
    return {"data": data}


@router.get("/cases/{jira_key}/alerts")
def get_case_alerts(
    jira_key: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_ai_data_token: str | None = Header(default=None, alias="X-AI-Data-Token"),
) -> dict[str, Any]:
    st = _settings()
    _require_read_access(st, authorization, x_ai_data_token)
    link, snapshot, bundle = _latest_case(st, jira_key)
    docs = _alert_docs(bundle.get("alerts"))
    page = docs[offset : offset + limit]
    return {
        "jira_key": link["jira_key"],
        "stellar_case_id": link["incident_id"],
        "snapshot_id": snapshot.get("snapshot_id"),
        "data": page,
        "pagination": {
            "total": len(docs),
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(docs) else None,
        },
    }
