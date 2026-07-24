"""Demo MVP API — dashboard and cases (real sync data)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import StellarSettings, get_stellar_settings
from app.demo.case_service import build_overview, get_case_detail, list_cases, sync_db_path
from app.demo.live_overview import build_live_overview
from app.demo.overview_query import parse_overview_query
from app.platform.deps import CurrentUser, require_full_session
from app.stellar.errors import StellarAPIError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/demo", tags=["demo"])


def _stellar_settings() -> StellarSettings:
    get_stellar_settings.cache_clear()
    return get_stellar_settings()


def _tenant_scope(current: CurrentUser) -> str | None:
    if current.is_platform_scope():
        return None
    return current.tenant_source_id


@router.get("/overview")
async def demo_overview(
    current: Annotated[CurrentUser, Depends(require_full_session)],
    st: StellarSettings = Depends(_stellar_settings),
    window: str = Query(default="12h", description="12h | 24h | 7d | all"),
    scope: str = Query(default="modified", description="modified | created"),
    new_basis: str = Query(default="created", description="created | modified"),
    source: str = Query(default="auto", description="auto | live | sync"),
) -> dict:
    try:
        query = parse_overview_query(window=window, scope=scope, new_basis=new_basis)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    tenant_source_id = _tenant_scope(current)
    prefer_live = source != "sync"
    force_sync = source == "sync"

    if prefer_live and not force_sync:
        try:
            return await build_live_overview(
                st,
                query,
                tenant_source_id=tenant_source_id,
            )
        except (StellarAPIError, RuntimeError, OSError) as e:
            logger.warning("live overview unavailable, falling back to sync: %s", e)
            if source == "live":
                raise HTTPException(status_code=503, detail="Stellar live overview failed") from e

    if not sync_db_path(st).is_file():
        raise HTTPException(status_code=503, detail="Sync state database not found")
    return build_overview(st, tenant_source_id=tenant_source_id, query=query)


@router.get("/cases")
def demo_cases(
    current: Annotated[CurrentUser, Depends(require_full_session)],
    st: StellarSettings = Depends(_stellar_settings),
    severity: str = Query(default=""),
    status: str = Query(default=""),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    if not sync_db_path(st).is_file():
        raise HTTPException(status_code=503, detail="Sync state database not found")
    return list_cases(
        st,
        tenant_source_id=_tenant_scope(current),
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
) -> dict:
    if not sync_db_path(st).is_file():
        raise HTTPException(status_code=503, detail="Sync state database not found")
    try:
        data = get_case_detail(
            st,
            case_id,
            tenant_source_id=_tenant_scope(current),
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    except LookupError:
        raise HTTPException(status_code=404, detail="Case not found") from None
    return {"data": data}
