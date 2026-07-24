"""Extract affected hosts/IPs from Stellar case bundles."""

from __future__ import annotations

from typing import Any


def _host_entry(host: Any) -> dict[str, str | None] | None:
    if not isinstance(host, dict):
        return None
    hostname = str(host.get("hostname") or "").strip() or None
    ip = str(host.get("ip") or "").strip() or None
    if not hostname and not ip:
        return None
    return {"hostname": hostname, "ip": ip}


def extract_affected_hosts(
    bundle: dict[str, Any] | None,
    *,
    limit: int = 20,
) -> list[dict[str, str | None]]:
    """Return deduplicated host rows from observables (hostname + ip)."""
    bundle = bundle or {}
    obs_payload = bundle.get("observables")
    obs = obs_payload.get("observables") if isinstance(obs_payload, dict) else None
    if not isinstance(obs, dict):
        return []
    seen: set[tuple[str | None, str | None]] = set()
    out: list[dict[str, str | None]] = []
    for host in obs.get("host") or []:
        if len(out) >= max(1, limit):
            break
        entry = _host_entry(host)
        if entry is None:
            continue
        key = (entry.get("hostname"), entry.get("ip"))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out
