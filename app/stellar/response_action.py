"""Stellar alert automated response action helpers (notify subject / disposition)."""

from __future__ import annotations

import re
from typing import Any

_BLOCKED_ACTION_RE = re.compile(
    r"\b(?:block(?:ed)?|kill(?:ed)?|prevent(?:ed)?|quarantine(?:d)?|terminate(?:d)?|"
    r"contain(?:ed)?|stop(?:ped)?|remediat(?:e|ed|ion)?|thwart(?:ed)?|"
    r"isolat(?:e|ed|ion)?|den(?:y|ied))\b",
    re.I,
)


def _alert_sources(bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    alerts_payload = (bundle or {}).get("alerts")
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    sources: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        if isinstance(src, dict):
            sources.append(src)
    return sources


def _response_action_from_alert_source(src: dict[str, Any]) -> str:
    pan = src.get("palo_alto_networks")
    if isinstance(pan, dict):
        for key in ("action_pretty", "action"):
            val = str(pan.get(key) or "").strip()
            if val:
                return val
    for key in ("action_pretty", "response_action", "alert_action", "auto_response"):
        val = src.get(key)
        if isinstance(val, list):
            parts = [str(x).strip() for x in val if str(x).strip()]
            if parts:
                return ", ".join(parts)
        elif val is not None:
            s = str(val).strip()
            if s:
                return s
    xdr = src.get("xdr_event")
    if isinstance(xdr, dict):
        desc = str(xdr.get("description") or "")
        m = re.search(r"Cortex XDR analysis:\s*\"?([^\".\n]+)\"?", desc)
        if m:
            return m.group(1).strip()
    return ""


def stellar_response_action_is_blocked(action_text: str) -> bool:
    """True when response action indicates attack was stopped (block/kill/prevent/…)."""
    text = str(action_text or "").strip()
    if not text:
        return False
    return bool(_BLOCKED_ACTION_RE.search(text))


def stellar_response_action_text(bundle: dict[str, Any] | None) -> str:
    """
    Representative response action for the case bundle.

    Prefer any blocked/prevented action over earlier Detected-only alerts.
    Stellar often lists Persistence (Detected, no Cortex case_id) before Malware
    (Prevented / with Cortex case_id); first-wins would mislabel SOC notify as 僅偵測.
    """
    first = ""
    for src in _alert_sources(bundle):
        text = _response_action_from_alert_source(src)
        if not text:
            continue
        if not first:
            first = text
        if stellar_response_action_is_blocked(text):
            return text
    return first


def stellar_notify_disposition_label(bundle: dict[str, Any] | None) -> str:
    """Subject suffix: ``已阻擋`` or ``僅偵測`` (any blocked alert wins)."""
    if stellar_response_action_is_blocked(stellar_response_action_text(bundle)):
        return "已阻擋"
    return "僅偵測"


def stellar_subject_detection_phrase(bundle: dict[str, Any] | None) -> str:
    if stellar_response_action_is_blocked(stellar_response_action_text(bundle)):
        return "已成功偵測並遏止"
    return "偵測到"
