"""Jira ``resolution tag`` (custom option) ↔ Stellar ``tags`` on cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MAP_PATH = _REPO_ROOT / "config" / "stellar_resolution_tag_map.json"


@dataclass(frozen=True)
class ResolutionTagMap:
    jira_field: str
    jira_option_by_value: bool
    jira_to_stellar: dict[str, str]
    stellar_to_jira: dict[str, str]
    on_resolve_stellar_status: str | None


def load_resolution_tag_map(path: Path | None = None) -> ResolutionTagMap:
    p = path or _DEFAULT_MAP_PATH
    if not p.is_file():
        return ResolutionTagMap(
            jira_field="customfield_10201",
            jira_option_by_value=True,
            jira_to_stellar={},
            stellar_to_jira={},
            on_resolve_stellar_status="Resolved",
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    jira_to: dict[str, str] = {}
    stellar_to: dict[str, str] = {}
    for row in data.get("pairs") or []:
        if not isinstance(row, dict):
            continue
        j = str(row.get("jira") or "").strip()
        t = str(row.get("stellar_tag") or "").strip()
        if j and t:
            jira_to[j] = t
            stellar_to[t] = j
            stellar_to[t.lower()] = j
    return ResolutionTagMap(
        jira_field=str(data.get("jira_field") or "customfield_10201"),
        jira_option_by_value=bool(data.get("jira_option_by_value", True)),
        jira_to_stellar=jira_to,
        stellar_to_jira=stellar_to,
        on_resolve_stellar_status=data.get("on_resolve_also_set_stellar_status") or "Resolved",
    )


def stellar_tags_from_case(case: dict[str, Any]) -> list[str]:
    raw = case.get("tags")
    if not isinstance(raw, list):
        return []
    return [str(t).strip() for t in raw if t is not None and str(t).strip()]


def jira_resolution_tag_from_case(case: dict[str, Any], tag_map: ResolutionTagMap) -> str | None:
    """First matching Stellar tag → Jira resolution tag option label."""
    for tag in stellar_tags_from_case(case):
        hit = tag_map.stellar_to_jira.get(tag) or tag_map.stellar_to_jira.get(tag.lower())
        if hit:
            return hit
        for jira_label, stellar_tag in tag_map.jira_to_stellar.items():
            if tag.lower() == stellar_tag.lower():
                return jira_label
    return None


def jira_field_payload_for_resolution_tag(label: str, tag_map: ResolutionTagMap) -> dict[str, str]:
    if tag_map.jira_option_by_value:
        return {"value": label}
    return {"name": label}


def jira_resolution_label_from_fields(
    fields: dict[str, Any], tag_map: ResolutionTagMap
) -> str | None:
    raw = fields.get(tag_map.jira_field)
    if isinstance(raw, dict):
        for key in ("value", "name"):
            v = raw.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return None


def stellar_put_body_for_jira_resolution_tag(
    jira_label: str,
    tag_map: ResolutionTagMap,
    *,
    current_tags: list[str] | None = None,
    apply_resolve_status: bool = True,
) -> dict[str, Any]:
    """Body fragment for ``PUT /cases/{id}`` when Jira resolution tag changes."""
    stellar_tag = tag_map.jira_to_stellar.get(jira_label)
    if not stellar_tag:
        return {}
    known = set(tag_map.jira_to_stellar.values())
    existing = current_tags or []
    to_delete = [t for t in existing if t in known and t != stellar_tag]
    tags_op: dict[str, list[str]] = {"add": [stellar_tag]}
    if to_delete:
        tags_op["delete"] = to_delete
    body: dict[str, Any] = {"tags": tags_op}
    if apply_resolve_status and jira_label != "None" and tag_map.on_resolve_stellar_status:
        body["status"] = tag_map.on_resolve_stellar_status
    return body
