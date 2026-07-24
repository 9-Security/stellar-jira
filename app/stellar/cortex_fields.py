"""Cortex XDR identifiers appearing inside Stellar alert bundles."""

from __future__ import annotations

from typing import Any


def _pan_from_alert_source(src: dict[str, Any]) -> dict[str, Any]:
    pan = src.get("palo_alto_networks")
    return pan if isinstance(pan, dict) else {}


def cortex_case_id_from_alert_source(src: dict[str, Any] | None) -> str:
    """Return Cortex XDR case id on an alert ``_source`` (empty if absent)."""
    if not isinstance(src, dict):
        return ""
    pan = _pan_from_alert_source(src)
    raw = pan.get("case_id")
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s or s.lower() in ("none", "null"):
        return ""
    return s


def _iter_alert_sources(bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    alerts_payload = (bundle or {}).get("alerts")
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    out: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        if isinstance(src, dict):
            out.append(src)
    return out


def stellar_bundle_has_cortex_case_id(bundle: dict[str, Any] | None) -> bool:
    """
    True if any alert in the Stellar case bundle carries a Cortex ``case_id``.

    Used to distinguish:
    - XDR-originated cases (blocked or detect-only) that usually have a Cortex case id
    - Stellar rule-elevated cases whose alerts often lack Cortex case id
    """
    for src in _iter_alert_sources(bundle):
        if cortex_case_id_from_alert_source(src):
            return True
    return False
