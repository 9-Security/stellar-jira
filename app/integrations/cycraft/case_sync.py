"""XCockpit Incident → Stellar Case sync (skeleton; create-case API not on 6.5.x)."""

from __future__ import annotations

import logging
from typing import Any

from app.integrations.cycraft.config import Settings
from app.integrations.cycraft.normalizer import normalize_incident
from app.integrations.cycraft.pipeline import ForwardPipeline
from app.integrations.cycraft.stellar_cases import StellarCasesClient
from app.integrations.cycraft.state import EventState

logger = logging.getLogger(__name__)

# XCockpit Incident state (API v2.1.0)
_XCOCKPIT_STATE_LABELS = {
    0: "InProgress",
    1: "Investigated",
    2: "Confirmed",
    3: "Closed",
    4: "Merged",
    5: "Reopened",
}

_STELLAR_STATUS_BY_XCOCKPIT = {
    0: "In Progress",
    1: "In Progress",
    2: "In Progress",
    3: "Resolved",
    4: "Resolved",
    5: "In Progress",
}


def incident_uuid(incident: dict[str, Any]) -> str:
    for key in ("uuid", "UUID"):
        value = incident.get(key)
        if value:
            return str(value).strip()
    return ""


def map_xcockpit_state_to_stellar(state: Any) -> str | None:
    try:
        code = int(state)
    except (TypeError, ValueError):
        return None
    return _STELLAR_STATUS_BY_XCOCKPIT.get(code)


class IncidentCaseSync:
    def __init__(self, settings: Settings, state: EventState, pipeline: ForwardPipeline) -> None:
        self._settings = settings
        self._state = state
        self._pipeline = pipeline
        self._cases: StellarCasesClient | None = None
        if settings.incident_case_sync_enabled:
            if not settings.stellar_cases_api_key.strip():
                raise ValueError(
                    "INCIDENT_CASE_SYNC_ENABLED=true requires STELLAR_CASES_API_KEY"
                )
            self._cases = StellarCasesClient(settings)

    async def handle_incident(self, incident: dict[str, Any]) -> dict[str, Any]:
        uuid = incident_uuid(incident)
        if not uuid:
            logger.warning("Skipping incident without uuid")
            return {"skipped": True, "reason": "missing_uuid"}

        title = str(incident.get("title") or incident.get("Title") or "XCockpit Incident")
        xstate = incident.get("state")
        xstate_label: str | None = None
        if xstate is not None:
            try:
                xstate_label = _XCOCKPIT_STATE_LABELS.get(int(xstate), str(xstate))
            except (TypeError, ValueError):
                xstate_label = str(xstate)

        self._state.upsert_incident_map(
            uuid,
            sync_status="observed",
            last_state=xstate_label,
        )

        if not self._settings.incident_case_sync_enabled:
            logger.info(
                "XCockpit incident observed uuid=%s title=%r state=%s (case sync disabled)",
                uuid,
                title,
                xstate_label,
            )
            return {"observed": True, "incident_uuid": uuid, "sync": "disabled"}

        mapped = self._state.get_incident_map(uuid)
        stellar_case_id = (mapped or {}).get("stellar_case_id")

        if stellar_case_id:
            if not self._cases:
                raise RuntimeError("Cases API client is not configured")
            return await self._sync_existing_case(uuid, stellar_case_id, incident, xstate_label)

        if self._settings.incident_maltrace_ingest:
            event = normalize_incident(
                incident,
                vendor=self._settings.stellar_xdr_vendor,
                source=self._settings.stellar_xdr_source,
            )
            ingest = await self._pipeline.forward_poll_item(
                {"kind": "incident", "payload": incident}
            )
            self._state.upsert_incident_map(
                uuid,
                sync_status="pending_case",
                last_state=xstate_label,
            )
            logger.info(
                "XCockpit incident uuid=%s ingested to maltrace; awaiting Stellar case correlation",
                uuid,
            )
            return {
                "incident_uuid": uuid,
                "sync": "pending_case",
                "maltrace": ingest,
                "event_id": event.get("event_id"),
            }

        self._state.upsert_incident_map(
            uuid,
            sync_status="pending_case",
            last_state=xstate_label,
        )
        logger.warning(
            "XCockpit incident uuid=%s has no Stellar case mapping; "
            "enable INCIDENT_MALTRACE_INGEST or set stellar_case_id manually. "
            "Stellar 6.5.x cannot create cases via API.",
            uuid,
        )
        return {"incident_uuid": uuid, "sync": "pending_case", "reason": "no_case_mapping"}

    async def _sync_existing_case(
        self,
        uuid: str,
        stellar_case_id: str,
        incident: dict[str, Any],
        xstate_label: str | None,
    ) -> dict[str, Any]:
        assert self._cases is not None
        body: dict[str, Any] = {}
        stellar_status = map_xcockpit_state_to_stellar(incident.get("state"))
        if stellar_status:
            body["status"] = stellar_status
        summary = incident.get("graph_summary") or incident.get("Graph_Summary")
        if summary:
            body["description"] = str(summary)
        tags = incident.get("tags") if isinstance(incident.get("tags"), list) else []
        if tags:
            body["tags"] = {"add": [f"cycraft:{t}" for t in tags[:10]]}

        try:
            if body:
                await self._cases.update_case(stellar_case_id, body)
            self._state.upsert_incident_map(
                uuid,
                stellar_case_id=stellar_case_id,
                sync_status="mapped",
                last_state=xstate_label,
            )
            logger.info(
                "Synced XCockpit incident uuid=%s -> Stellar case %s status=%s",
                uuid,
                stellar_case_id,
                stellar_status,
            )
            return {
                "incident_uuid": uuid,
                "stellar_case_id": stellar_case_id,
                "sync": "mapped",
                "updated": list(body.keys()),
            }
        except Exception as exc:
            self._state.upsert_incident_map(
                uuid,
                stellar_case_id=stellar_case_id,
                sync_status="error",
                last_state=xstate_label,
            )
            logger.exception("Failed to sync incident uuid=%s to case %s", uuid, stellar_case_id)
            return {
                "incident_uuid": uuid,
                "stellar_case_id": stellar_case_id,
                "sync": "error",
                "error": str(exc),
            }
