"""Resolve middleware case numbers (XSOC-*) for demo UI."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CaseNumberIndex:
    by_stellar: dict[str, str] = field(default_factory=dict)
    by_jira: dict[str, str] = field(default_factory=dict)
    by_middleware: dict[str, str] = field(default_factory=dict)

    def middleware_for(
        self,
        *,
        stellar_case_id: str | None = None,
        jira_key: str | None = None,
    ) -> str | None:
        sid = str(stellar_case_id or "").strip()
        if sid and sid in self.by_stellar:
            return self.by_stellar[sid]
        jk = str(jira_key or "").strip()
        if jk:
            hit = self.by_jira.get(jk.upper()) or self.by_jira.get(jk)
            if hit:
                return hit
        return None

    def stellar_for_middleware(self, case_number: str) -> str | None:
        key = str(case_number or "").strip()
        if not key:
            return None
        return self.by_middleware.get(key.upper()) or self.by_middleware.get(key)


def load_case_number_index(path: Path, source_id: str) -> CaseNumberIndex:
    """Load latest middleware_case_id per stellar case / jira key."""
    index = CaseNumberIndex()
    if not path.is_file():
        return index
    sid = str(source_id or "stellar").strip() or "stellar"
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) as db:
        has_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_events' LIMIT 1"
        ).fetchone()
        if not has_table:
            return index
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT stellar_case_id, middleware_case_id, jira_key, created_at "
            "FROM decision_events "
            "WHERE source_id=? AND middleware_case_id IS NOT NULL AND TRIM(middleware_case_id) != '' "
            "ORDER BY created_at DESC",
            (sid,),
        ).fetchall()
    for row in rows:
        mid = str(row["middleware_case_id"] or "").strip()
        if not mid:
            continue
        stellar = str(row["stellar_case_id"] or "").strip()
        jira = str(row["jira_key"] or "").strip()
        if stellar and stellar not in index.by_stellar:
            index.by_stellar[stellar] = mid
        if jira:
            index.by_jira.setdefault(jira.upper(), mid)
        index.by_middleware.setdefault(mid.upper(), stellar)
    return index


def display_case_number(
    *,
    stellar_case_id: str | None = None,
    jira_key: str | None = None,
    middleware_case_id: str | None = None,
    index: CaseNumberIndex | None = None,
) -> str:
    """Human-facing case id (XSOC-* preferred, then Jira key). Never Stellar _id."""
    mid = str(middleware_case_id or "").strip()
    if not mid and index is not None:
        mid = index.middleware_for(
            stellar_case_id=stellar_case_id,
            jira_key=jira_key,
        ) or ""
    if mid:
        return mid
    jk = str(jira_key or "").strip()
    if jk:
        return jk
    return ""


def case_route_id(
    *,
    stellar_case_id: str | None = None,
    jira_key: str | None = None,
    middleware_case_id: str | None = None,
    index: CaseNumberIndex | None = None,
) -> str:
    """URL segment for /cases/{id} — prefers XSOC, then Jira, then Stellar _id."""
    label = display_case_number(
        stellar_case_id=stellar_case_id,
        jira_key=jira_key,
        middleware_case_id=middleware_case_id,
        index=index,
    )
    if label:
        return label
    return str(stellar_case_id or jira_key or "").strip()


def enrich_case_row(row: dict[str, Any], index: CaseNumberIndex | None) -> dict[str, Any]:
    mid = None
    if index is not None:
        mid = index.middleware_for(
            stellar_case_id=str(row.get("stellar_case_id") or ""),
            jira_key=str(row.get("jira_key") or "") or None,
        )
    number = display_case_number(
        stellar_case_id=str(row.get("stellar_case_id") or "") or None,
        jira_key=str(row.get("jira_key") or "") or None,
        middleware_case_id=mid,
        index=index,
    )
    route_id = case_route_id(
        stellar_case_id=str(row.get("stellar_case_id") or "") or None,
        jira_key=str(row.get("jira_key") or "") or None,
        middleware_case_id=mid,
        index=index,
    )
    out = dict(row)
    out["middleware_case_id"] = mid
    out["case_number"] = number or None
    out["case_ref"] = route_id or None
    return out


def resolve_case_lookup_key(
    case_id: str,
    *,
    path: Path,
    source_id: str,
) -> str:
    """Map XSOC case number (or pass-through jira / stellar id) to lookup key."""
    key = str(case_id or "").strip()
    if not key:
        return key
    if not path.is_file():
        return key
    index = load_case_number_index(path, source_id)
    stellar = index.stellar_for_middleware(key)
    if stellar:
        return stellar
    upper = key.upper()
    if upper in index.by_jira:
        return index.by_jira[upper]
    return key
