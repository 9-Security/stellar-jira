"""Multi-tenant CyCraft poller — one isolated profile per enabled tenant."""

from __future__ import annotations

import asyncio
import logging

from app.config import get_platform_settings
from app.integrations.cycraft.config import load_settings
from app.integrations.cycraft.tenant_config import (
    build_tenant_settings,
    tenant_cycraft_configured,
)
from app.platform.store import PlatformStore

logger = logging.getLogger(__name__)


def _enabled_tenant_rows() -> list[tuple[str, dict]]:
    ps = get_platform_settings()
    if not ps.platform_enabled:
        return []
    store = PlatformStore(ps.db_path_resolved())
    store.init()
    out: list[tuple[str, dict]] = []
    for row in store.list_cycraft_enabled_integrations():
        tid = str(row.get("tenant_source_id") or "").strip()
        if not tid:
            continue
        if tenant_cycraft_configured(tid, row):
            out.append((tid, row))
        else:
            logger.warning(
                "tenant %s CyCraft enabled but config incomplete (check UI + per-tenant env)",
                tid,
            )
    return out


async def run_multi_tenant_poller() -> None:
    master = load_settings()
    interval = max(5, master.xcockpit_poll_interval_seconds)
    logger.info(
        "CyCraft multi-tenant poller started (master=%s interval=%ss)",
        master.cycraft_connector_enabled,
        interval,
    )
    while True:
        if not master.cycraft_connector_enabled:
            await asyncio.sleep(interval)
            continue
        profiles = _enabled_tenant_rows()
        if not profiles:
            logger.info("No tenant with complete CyCraft config; sleeping %ss", interval)
            await asyncio.sleep(interval)
            continue
        for tid, row in profiles:
            settings = build_tenant_settings(tid, row)
            logger.info("CyCraft poll cycle for tenant=%s", tid)
            try:
                await _run_single_cycle(settings)
            except Exception:
                logger.exception("CyCraft poll failed for tenant=%s", tid)
        await asyncio.sleep(interval)


async def _run_single_cycle(settings) -> None:
    """One alert/incident poll cycle for a tenant-scoped Settings instance."""
    from app.integrations.cycraft.case_sync import IncidentCaseSync
    from app.integrations.cycraft.pipeline import ForwardPipeline
    from app.integrations.cycraft.poller import _poll_alerts, _poll_incidents
    from app.integrations.cycraft.xcockpit_client import XCockpitClient

    xcockpit = XCockpitClient(settings)
    pipeline = ForwardPipeline(settings)
    case_sync = IncidentCaseSync(settings, pipeline.state, pipeline)
    mode = settings.xcockpit_poll_mode
    state = pipeline.state
    try:
        if mode in ("alerts", "both"):
            await _poll_alerts(xcockpit, pipeline, state)
        if mode in ("incidents", "both"):
            await _poll_incidents(xcockpit, case_sync, state)
    finally:
        await xcockpit.aclose()
        await pipeline.aclose()
        pipeline.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_multi_tenant_poller())
