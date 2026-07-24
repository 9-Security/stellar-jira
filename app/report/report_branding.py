"""Shared monthly report cover / platform labels."""

from __future__ import annotations

REPORT_COVER_TITLE = "XMDR 託管式偵測與回應服務"


def report_platform(vendor: str) -> str:
    """e.g. ``Darktrace via AI SOC``."""
    label = str(vendor or "").strip()
    if not label:
        label = "XMDR"
    return f"{label} via AI SOC"
