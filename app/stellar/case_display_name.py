"""Human-readable alert names from Stellar ``case.name`` (strip vendor prefix / multi-alert suffix)."""

from __future__ import annotations

import re
from typing import Any

_MULTI_ALERT_SUFFIX_RE = re.compile(r"\s+and\s+\d+\s+others?\s*$", re.I)

_VENDOR_KEYWORDS = (
    "networks",
    "cortex",
    "xdr",
    "darktrace",
    "carbon black",
    "defender",
    "crowdstrike",
    "sentinel",
    "microsoft",
    "palo alto",
    "fortinet",
    "splunk",
    "symantec",
    "trend micro",
    "mcafee",
    "elastic",
    "sentinelone",
    "cybereason",
)

_XDR_IDENTIFIED_RE = re.compile(r'identified\s+"([^"]+)"', re.I)
_XDR_DETECTED_RE = re.compile(r'detected\s+"([^"]+)"', re.I)


def _strip_multi_alert_suffix(text: str) -> str:
    return _MULTI_ALERT_SUFFIX_RE.sub("", text).strip()


def _looks_like_vendor_prefix(left: str) -> bool:
    left = left.strip()
    if not left or len(left) > 120:
        return False
    lower = left.lower()
    if lower == "darktrace" or lower.startswith("darktrace "):
        return True
    if any(keyword in lower for keyword in _VENDOR_KEYWORDS):
        return True
    if "(" in left and ")" in left:
        return True
    if len(left.split()) <= 5 and left[0].isupper():
        return True
    return False


def _strip_vendor_prefix(text: str) -> str:
    if ": " in text:
        left, right = text.split(": ", 1)
        if right.strip() and _looks_like_vendor_prefix(left):
            return right.strip()
    if ":" in text:
        left, right = text.split(":", 1)
        if right.strip() and _looks_like_vendor_prefix(left):
            return right.strip()
    return text


def _alert_name_from_xdr_description(desc: str) -> str:
    for pattern in (_XDR_IDENTIFIED_RE, _XDR_DETECTED_RE):
        m = pattern.search(desc)
        if m:
            name = m.group(1).strip()
            if name:
                return name
    return ""


def _alert_name_from_bundle(bundle: dict[str, Any] | None) -> str:
    alerts_payload = (bundle or {}).get("alerts")
    if not isinstance(alerts_payload, dict):
        return ""
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        if not isinstance(src, dict):
            continue
        for key in ("name", "display_name", "title", "rule_name"):
            val = str(src.get(key) or "").strip()
            if val:
                return val
        xdr = src.get("xdr_event")
        if isinstance(xdr, dict):
            from_name = _alert_name_from_xdr_description(str(xdr.get("description") or ""))
            if from_name:
                return from_name
        pan = src.get("palo_alto_networks")
        if isinstance(pan, dict):
            for key in ("bioc_indicator", "description"):
                val = str(pan.get(key) or "").strip()
                if val and len(val) <= 200:
                    return val
    return ""


def clean_stellar_case_name(raw: str) -> str:
    """Strip Stellar multi-alert suffix and vendor/product prefix from ``case.name``."""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = _strip_multi_alert_suffix(text)
    return _strip_vendor_prefix(text).strip()


def stellar_case_display_name(
    case: dict[str, Any] | None,
    bundle: dict[str, Any] | None = None,
    *,
    default: str = "Stellar Case",
) -> str:
    """Display alert name for notify / Jira (cleaned ``case.name``, alert fallback)."""
    raw = str((case or {}).get("name") or "").strip()
    if not raw:
        fallback = _alert_name_from_bundle(bundle)
        return fallback or default
    cleaned = clean_stellar_case_name(raw)
    if cleaned:
        return cleaned
    fallback = _alert_name_from_bundle(bundle)
    if fallback:
        return fallback
    return raw or default
