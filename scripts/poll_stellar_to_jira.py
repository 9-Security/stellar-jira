#!/usr/bin/env python3
"""One-shot: poll Stellar Cyber and create Jira issues for new cases."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.stellar_sync.runner import run_stellar_to_jira_sync  # noqa: E402


async def main() -> int:
    p = argparse.ArgumentParser(description="Poll Stellar Cyber → Jira AIxSOC (one cycle)")
    p.add_argument("--dry-run", action="store_true", help="Do not create issues or advance watermark")
    args = p.parse_args()
    out = await run_stellar_to_jira_sync(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
