#!/usr/bin/env python3
"""Run CyCraft XCockpit → Stellar XDR connector poller (stellar-jira integrated)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.integrations.cycraft.poller import main

if __name__ == "__main__":
    main()
