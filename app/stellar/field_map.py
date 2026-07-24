"""Load Stellar ↔ Jira custom field id map (JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_stellar_jira_field_map(repo_root: Path, path: str | None) -> dict[str, str]:
    rel = (path or "config/stellar_jira_field_map.example.json").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = repo_root / p
    if not p.is_file():
        return {
            "severity": "customfield_10057",
            "status": "customfield_10061",
        }
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("severity", "status", "name", "case_id", "resolution_tag"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out
