"""Shared forward pipeline: normalize → dedupe → Stellar ingest."""

from __future__ import annotations

import logging
from typing import Any

from app.integrations.cycraft.config import Settings
from app.integrations.cycraft.normalizer import (
    event_for_stellar_ingest,
    normalize_cycraft_event,
    normalize_csr_report,
    normalize_edr_alert_report,
    normalize_incident,
)
from app.integrations.cycraft.stellar_xdr import StellarXDRClient
from app.integrations.cycraft.state import EventState

logger = logging.getLogger(__name__)


class ForwardPipeline:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stellar = StellarXDRClient(settings)
        self._state = EventState(settings.connector_state_db)

    async def aclose(self) -> None:
        await self._stellar.aclose()

    def close(self) -> None:
        self._state.close()

    @property
    def state(self) -> EventState:
        return self._state

    async def forward_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
        events = self._normalize_payload(payload)
        results = []
        for event in events:
            results.append(await self._forward_event(event))
        if len(results) == 1:
            return results[0]
        return {"count": len(results), "results": results}

    async def forward_poll_item(self, item: dict[str, Any]) -> dict[str, Any]:
        kind = item.get("kind")
        payload = item.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("poll item missing payload dict")
        if kind == "edr_alert":
            events = normalize_edr_alert_report(
                payload,
                vendor=self._settings.stellar_xdr_vendor,
                source=self._settings.stellar_xdr_source,
            )
        elif kind == "csr_report":
            events = normalize_csr_report(
                payload,
                vendor=self._settings.stellar_xdr_vendor,
                source=self._settings.stellar_xdr_source,
            )
        elif kind == "incident":
            events = [
                normalize_incident(
                    payload,
                    vendor=self._settings.stellar_xdr_vendor,
                    source=self._settings.stellar_xdr_source,
                )
            ]
        else:
            events = self._normalize_payload(payload)
        results = []
        for event in events:
            results.append(await self._forward_event(event))
        if len(results) == 1:
            return results[0]
        return {"count": len(results), "results": results}

    def _normalize_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if payload.get("ReportType") == "CYCRAFT_E":
            return normalize_edr_alert_report(
                payload,
                vendor=self._settings.stellar_xdr_vendor,
                source=self._settings.stellar_xdr_source,
            )
        if payload.get("ReportType") == "CYCRAFT_C":
            return normalize_csr_report(
                payload,
                vendor=self._settings.stellar_xdr_vendor,
                source=self._settings.stellar_xdr_source,
            )
        if payload.get("uuid") and (
            payload.get("computer_name") or payload.get("Computer_Name")
        ):
            return [
                normalize_incident(
                    payload,
                    vendor=self._settings.stellar_xdr_vendor,
                    source=self._settings.stellar_xdr_source,
                )
            ]
        return [
            normalize_cycraft_event(
                payload,
                vendor=self._settings.stellar_xdr_vendor,
                source=self._settings.stellar_xdr_source,
            )
        ]

    async def _forward_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_key = str(event.get("event_id"))
        if self._state.seen(event_key):
            logger.info("Skip duplicate event_id=%s", event_key)
            return {"skipped": True, "event_id": event_key}
        ingest_body = event_for_stellar_ingest(event)
        result = await self._stellar.ingest(ingest_body)
        self._state.mark_sent(event_key)
        return {"skipped": False, "event_id": event_key, "stellar": result}
