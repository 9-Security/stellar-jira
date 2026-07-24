"""Dashboard window / scope query parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

VALID_WINDOWS = frozenset({"12h", "24h", "7d", "all"})
VALID_SCOPE = frozenset({"modified", "created"})
VALID_NEW_BASIS = frozenset({"created", "modified"})

_WINDOW_HOURS = {"12h": 12, "24h": 24, "7d": 24 * 7}


@dataclass(frozen=True)
class OverviewQuery:
    window: str
    scope: str
    new_basis: str
    since_ms: int | None
    since_iso: str | None

    @property
    def scope_field(self) -> str:
        return "modified_at" if self.scope == "modified" else "created_at"

    @property
    def new_basis_field(self) -> str:
        return "created_at" if self.new_basis == "created" else "modified_at"


def parse_overview_query(
    *,
    window: str = "12h",
    scope: str = "modified",
    new_basis: str = "created",
) -> OverviewQuery:
    w = str(window or "12h").strip().lower()
    sc = str(scope or "modified").strip().lower()
    nb = str(new_basis or "created").strip().lower()
    if w not in VALID_WINDOWS:
        raise ValueError(f"invalid window: {window}")
    if sc not in VALID_SCOPE:
        raise ValueError(f"invalid scope: {scope}")
    if nb not in VALID_NEW_BASIS:
        raise ValueError(f"invalid new_basis: {new_basis}")

    since_ms: int | None = None
    since_iso: str | None = None
    if w != "all":
        hours = _WINDOW_HOURS[w]
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        since_ms = int(since.timestamp() * 1000)
        since_iso = since.replace(microsecond=0).isoformat()

    return OverviewQuery(
        window=w,
        scope=sc,
        new_basis=nb,
        since_ms=since_ms,
        since_iso=since_iso,
    )
