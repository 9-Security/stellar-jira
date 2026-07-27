"""Backward-compatible shim — use XCockpitClient."""

from app.integrations.cycraft.xcockpit_client import XCockpitClient as CyCraftClient

__all__ = ["CyCraftClient"]
