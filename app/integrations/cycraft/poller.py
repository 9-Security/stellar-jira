"""Background poller: XCockpit API → Stellar XDR / Case sync."""

from __future__ import annotations

import asyncio
import logging

from app.integrations.cycraft.case_sync import IncidentCaseSync
from app.integrations.cycraft.config import Settings, load_settings, validate_settings
from app.integrations.cycraft.platform_gate import any_tenant_cycraft_enabled
from app.integrations.cycraft.pipeline import ForwardPipeline
from app.integrations.cycraft.watermark import (
    WATERMARK_ALERTS,
    WATERMARK_INCIDENTS,
    bump_alert_watermark,
    bump_incident_watermark,
    resolve_watermark,
)
from app.integrations.cycraft.xcockpit_client import XCockpitClient, _format_xcockpit_datetime

logger = logging.getLogger(__name__)


async def run_poller(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    validate_settings(settings)
    xcockpit = XCockpitClient(settings)
    pipeline = ForwardPipeline(settings)
    case_sync = IncidentCaseSync(settings, pipeline.state, pipeline)
    interval = max(5, settings.xcockpit_poll_interval_seconds)
    state = pipeline.state
    mode = settings.xcockpit_poll_mode

    logger.info(
        "XCockpit poller started mode=%s interval=%ss incident_sync=%s enabled=%s",
        mode,
        interval,
        settings.incident_case_sync_enabled,
        settings.cycraft_connector_enabled,
    )
    try:
        while True:
            if not settings.cycraft_connector_enabled or not any_tenant_cycraft_enabled():
                logger.info(
                    "CyCraft connector idle (master switch or no tenant enabled); sleeping %ss",
                    interval,
                )
                await asyncio.sleep(interval)
                continue
            if mode in ("alerts", "both"):
                try:
                    await _poll_alerts(xcockpit, pipeline, state)
                except Exception:
                    logger.exception("Alert poll cycle failed")
            if mode in ("incidents", "both"):
                try:
                    await _poll_incidents(xcockpit, case_sync, state)
                except Exception:
                    logger.exception("Incident poll cycle failed")
            await asyncio.sleep(interval)
    finally:
        await xcockpit.aclose()
        await pipeline.aclose()
        pipeline.close()


async def _poll_alerts(
    xcockpit: XCockpitClient,
    pipeline: ForwardPipeline,
    state,
) -> None:
    created_after = resolve_watermark(
        state,
        WATERMARK_ALERTS,
        default=xcockpit.default_created_after(),
    )
    batch = await xcockpit.fetch_alert_items(created_after)
    logger.info(
        "XCockpit alert poll batch size=%s since=%s",
        len(batch),
        created_after.isoformat(),
    )
    latest = created_after
    for item in batch:
        try:
            await pipeline.forward_poll_item(item)
        except Exception:
            logger.exception("Failed to forward alert item")
            break
        latest = bump_alert_watermark(latest, item)
        state.set_watermark(WATERMARK_ALERTS, _format_xcockpit_datetime(latest))


async def _poll_incidents(
    xcockpit: XCockpitClient,
    case_sync: IncidentCaseSync,
    state,
) -> None:
    created_after = resolve_watermark(
        state,
        WATERMARK_INCIDENTS,
        legacy_key=None,
        default=xcockpit.default_created_after(),
    )
    batch = await xcockpit.fetch_incident_items(created_after)
    logger.info(
        "XCockpit incident poll batch size=%s since=%s",
        len(batch),
        created_after.isoformat(),
    )
    latest = created_after
    for item in batch:
        try:
            await case_sync.handle_incident(item["payload"])
        except Exception:
            logger.exception("Failed to handle incident item")
            break
        latest = bump_incident_watermark(latest, item)
        state.set_watermark(WATERMARK_INCIDENTS, _format_xcockpit_datetime(latest))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from app.integrations.cycraft.multi_poller import main as multi_main

    multi_main()


if __name__ == "__main__":
    main()
