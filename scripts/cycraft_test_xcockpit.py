#!/usr/bin/env python3
"""Probe XCockpit API (no Stellar POST)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.integrations.cycraft.config import load_settings, validate_settings
from app.integrations.cycraft.xcockpit_client import XCockpitClient


async def _run() -> None:
    settings = load_settings()
    validate_settings(settings)
    client = XCockpitClient(settings)
    try:
        created_after = client.default_created_after()
        batch = await client.fetch_alert_items(created_after)
        print(f"OK: alert batch size={len(batch)} since={created_after.isoformat()}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(_run())
