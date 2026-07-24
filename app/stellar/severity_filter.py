"""Stellar case severity gating for Jira create + SOC notify."""

from __future__ import annotations

import re
from typing import Any

_STELLAR_SEVERITY_LABELS = ("Critical", "High", "Medium", "Low")


def normalize_stellar_severity(severity: object) -> str:
    s = str(severity or "").strip()
    if not s:
        return ""
    for label in _STELLAR_SEVERITY_LABELS:
        if s.lower() == label.lower():
            return label
    return s.capitalize() if s.isascii() else s


def parse_allowed_severities(raw: str | None) -> frozenset[str] | None:
    """
    Parse ``STELLAR_SYNC_ALLOWED_SEVERITIES``.

    Returns ``None`` when all severities are allowed (empty or ``*``).
    """
    s = str(raw or "").strip()
    if not s or s == "*":
        return None
    out: set[str] = set()
    for part in re.split(r"[,;\s]+", s):
        label = normalize_stellar_severity(part)
        if label in _STELLAR_SEVERITY_LABELS:
            out.add(label)
    if not out:
        return None
    return frozenset(out)


def case_severity_allowed(case: dict[str, Any], allowed: frozenset[str] | None) -> bool:
    if allowed is None:
        return True
    label = normalize_stellar_severity(case.get("severity"))
    return label in allowed


_SEVERITY_RANK = {label: idx for idx, label in enumerate(reversed(_STELLAR_SEVERITY_LABELS))}


def severity_rank(severity: object) -> int:
    """Higher = more severe. Unknown labels rank 0."""
    label = normalize_stellar_severity(severity)
    return int(_SEVERITY_RANK.get(label, 0))


def is_severity_escalation(previous: object, current: object) -> bool:
    """True when ``current`` is strictly higher than ``previous`` (e.g. Medium → High)."""
    prev = normalize_stellar_severity(previous)
    curr = normalize_stellar_severity(current)
    if not prev or not curr:
        return False
    return severity_rank(curr) > severity_rank(prev)
