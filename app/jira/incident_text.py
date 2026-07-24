"""Format Cortex incident host/user lists for Jira text fields and SOC email (no Cortex Settings)."""

from __future__ import annotations

from typing import Any


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def format_affected_hosts(incident: dict[str, Any]) -> str:
    """Cortex ``hosts`` entries are often ``hostname:agent_id``; Jira shows hostnames only."""
    raw = incident.get("hosts")
    if not isinstance(raw, list):
        return str(raw).strip() if raw else ""
    names: list[str] = []
    for h in raw:
        if h is None:
            continue
        s = str(h).strip()
        if not s:
            continue
        name = s.split(":", 1)[0].strip() if ":" in s else s
        if name:
            names.append(name)
    return "\n".join(_unique_preserve_order(names))


def _user_display_name(entry: str) -> str:
    s = entry.strip()
    if not s:
        return ""
    if "\\" in s:
        return s.split("\\", 1)[-1].strip()
    if "/" in s:
        return s.rsplit("/", 1)[-1].strip()
    return s


def format_affected_users(incident: dict[str, Any]) -> str:
    raw = incident.get("users")
    if not isinstance(raw, list):
        return str(raw).strip() if raw else ""
    names: list[str] = []
    for u in raw:
        if u is None:
            continue
        name = _user_display_name(str(u))
        if name:
            names.append(name)
    return "\n".join(_unique_preserve_order(names))
