"""Stellar Cyber ↔ Jira only (no Cortex routes)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.config import get_notify_settings, get_platform_settings, get_stellar_settings
from app.routers import admin_users as admin_users_router
from app.routers import ai_data as ai_data_router
from app.routers import demo as demo_router
from app.routers import line_webhook as line_webhook_router
from app.routers import platform_auth as platform_auth_router
from app.routers import stellar_webhook as stellar_webhook_router
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.platform.store import PlatformStore
from app.spa_static import SPAStaticFiles
from app.sync.state import SyncState

logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEAK_PLATFORM_SECRETS = frozenset({
    "change-me-in-production",
    "change-me-to-a-long-random-string",
})


def _validate_platform_security(ps) -> None:
    if not ps.platform_enabled:
        return
    secret = str(ps.platform_secret_key or "").strip()
    if len(secret) < 32 or secret in _WEAK_PLATFORM_SECRETS:
        logger.error(
            "PLATFORM_SECRET_KEY is missing or weak (need >=32 chars, not default). "
            "Platform login is unsafe until fixed."
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    if not st.sync_api_token and not st.stellar_webhook_token:
        logger.warning(
            "STELLAR_WEBHOOK_TOKEN / SYNC_API_TOKEN not set; "
            "POST /v1/webhooks/jira-stellar will return 503"
        )
    get_notify_settings.cache_clear()
    ns = get_notify_settings()
    if not (ns.line_channel_secret or "").strip():
        logger.warning(
            "LINE_CHANNEL_SECRET not set; POST /v1/webhooks/line will return 503"
        )
    get_platform_settings.cache_clear()
    ps = get_platform_settings()
    if ps.platform_enabled:
        _validate_platform_security(ps)
        try:
            PlatformStore(ps.db_path_resolved()).init()
        except OSError as e:
            logger.warning("platform db init failed: %s", e)
    yield


app = FastAPI(
    title="stellar-jira",
    version="0.1.0",
    description="Stellar Cyber → Jira AIxSOC middleware.",
    lifespan=_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(SecurityHeadersMiddleware)

app.include_router(stellar_webhook_router.router)
app.include_router(line_webhook_router.router)
app.include_router(ai_data_router.router)
app.include_router(platform_auth_router.router)
app.include_router(demo_router.router)
app.include_router(admin_users_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict[str, object]:
    """Process + local state DB writable (does not call Stellar Cases LIST)."""
    issues: list[str] = []
    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    if not st.stellar_base_url or not st.stellar_api_key:
        issues.append("STELLAR_BASE_URL or STELLAR_API_KEY not configured")
    db_path = _REPO_ROOT / st.stellar_sync_state_db
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        state = SyncState(db_path)
        state.init(legacy_source_id=st.stellar_poll_source_id or "stellar")
    except OSError as e:
        issues.append(f"state_db: {e}")
    if issues:
        raise HTTPException(status_code=503, detail={"ready": False, "issues": issues})
    return {"ready": True}


_web_dist = _REPO_ROOT / "web" / "dist"
if _web_dist.is_dir():
    app.mount(
        "/",
        SPAStaticFiles(directory=str(_web_dist), html=True),
        name="ui",
    )
