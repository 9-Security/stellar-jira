#!/usr/bin/env python3
"""Stellar→Jira automation: one shot (default) or interval polling until SIGINT/SIGTERM."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_stellar_settings  # noqa: E402
from app.stellar_sync.automation_service import run_stellar_automation_service  # noqa: E402


def _resolve_interval_seconds(cli_interval: int | None) -> int | None:
    if cli_interval is not None:
        return cli_interval
    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    if st.stellar_automation_interval_seconds is not None:
        return int(st.stellar_automation_interval_seconds)
    return None


def main() -> None:
    get_stellar_settings.cache_clear()
    st = get_stellar_settings()
    min_sec = int(st.stellar_automation_min_interval_seconds)

    p = argparse.ArgumentParser(
        description="Stellar↔Jira automation: poll Stellar for new cases (create Jira) "
        "and optionally Jira→Stellar field write-back each cycle. "
        "Interval: --interval SEC or STELLAR_AUTOMATION_INTERVAL_SECONDS in .env."
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--interval", type=int, default=None, metavar="SEC")
    args = p.parse_args()
    interval = _resolve_interval_seconds(args.interval)
    if interval is not None and interval < min_sec:
        p.error(f"--interval must be at least {min_sec} (STELLAR_AUTOMATION_MIN_INTERVAL_SECONDS)")
    code = asyncio.run(
        run_stellar_automation_service(interval_seconds=interval, dry_run=args.dry_run)
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
