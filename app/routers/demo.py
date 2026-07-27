"""Demo MVP API — dashboard and cases (real sync data)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import StellarSettings, get_stellar_settings
from app.demo.case_service import build_overview, get_case_detail, list_cases, sync_db_path
from app.demo.live_overview import build_live_overview
from app.demo.overview_query import parse_overview_query
from app.demo.tenant_access import effective_tenant_source_id, list_visible_tenants
from app.platform.deps import CurrentUser, require_full_session
from app.stellar.errors import StellarAPIError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/demo", tags=["demo"])


def _stellar_settings() -> StellarSettings:
    get_stellar_settings.cache_clear()
    return get_stellar_settings()


@router.get("/tenants")
def demo_tenants(
    current: Annotated[CurrentUser, Depends(require_full_session)],
    st: StellarSettings = Depends(_stellar_settings),
) -> dict:
    return {"data": list_visible_tenants(st, current)}


@router.get("/overview")
async def demo_overview(
    current: Annotated[CurrentUser, Depends(require_full_session)],
    st: StellarSettings = Depends(_stellar_settings),
    window: str = Query(default="12h", description="12h | 24h | 7d | all"),
    scope: str = Query(default="modified", description="modified | created"),
    new_basis: str = Query(default="created", description="created | modified"),
    source: str = Query(default="auto", description="auto | live | sync"),
    tenant: str = Query(default="", description="tenant source_id (platform scope)"),
) -> dict:
    try:
        query = parse_overview_query(window=window, scope=scope, new_basis=new_basis)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    tenant_source_id = effective_tenant_source_id(current, tenant or None)
    prefer_live = source != "sync"
    force_sync = source == "sync"

    if prefer_live and not force_sync:
        try:
            payload = await build_live_overview(
                st,
                query,
                tenant_source_id=tenant_source_id,
            )
        except (StellarAPIError, RuntimeError, OSError) as e:
            logger.warning("live overview unavailable, falling back to sync: %s", e)
            if source == "live":
                raise HTTPException(status_code=503, detail="Stellar live overview failed") from e
            payload = None
        else:
            if tenant_source_id:
                payload.setdefault("meta", {})["tenant_source_id"] = tenant_source_id
            return payload

    if not sync_db_path(st).is_file():
        raise HTTPException(status_code=503, detail="Sync state database not found")
    payload = build_overview(st, tenant_source_id=tenant_source_id, query=query)
    if tenant_source_id:
        payload.setdefault("meta", {})["tenant_source_id"] = tenant_source_id
    return payload


@router.get("/cases")
def demo_cases(
    current: Annotated[CurrentUser, Depends(require_full_session)],
    st: StellarSettings = Depends(_stellar_settings),
    severity: str = Query(default=""),
    status: str = Query(default=""),
    q: str = Query(default="", max_length=200),
    tenant: str = Query(default="", description="tenant source_id (platform scope)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    if not sync_db_path(st).is_file():
        raise HTTPException(status_code=503, detail="Sync state database not found")
    tenant_source_id = effective_tenant_source_id(current, tenant or None)
    return list_cases(
        st,
        tenant_source_id=tenant_source_id,
        severity=severity or None,
        status=status or None,
        q=q or None,
        limit=limit,
        offset=offset,
    )


@router.get("/cases/{case_id}")
def demo_case_detail(
    case_id: str,
    current: Annotated[CurrentUser, Depends(require_full_session)],
    st: StellarSettings = Depends(_stellar_settings),
    tenant: str = Query(default="", description="tenant source_id (platform scope)"),
) -> dict:
    if not sync_db_path(st).is_file():
        raise HTTPException(status_code=503, detail="Sync state database not found")
    tenant_source_id = effective_tenant_source_id(current, tenant or None)
    try:
        data = get_case_detail(
            st,
            case_id,
            tenant_source_id=tenant_source_id,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    except LookupError:
        raise HTTPException(status_code=404, detail="Case not found") from None
    return {"data": data}
