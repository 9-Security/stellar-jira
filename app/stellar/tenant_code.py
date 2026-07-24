"""Map Stellar case tenant to middleware 客戶代號 (customer_code for case IDs and summary)."""

from __future__ import annotations

import re
from typing import Any

_CUSTOMER_CODE_RE = re.compile(r"^[A-Z0-9]{2,16}$")


def customer_code_from_case(case: dict[str, Any], *, default: str | None = None) -> str:
    """
    Prefer ``tenant_name`` (Stellar UI tenant label, e.g. JJNET) as 客戶代號.
    Fallback: ``cust_id`` truncated, then ``default``.
    """
    for raw in (case.get("tenant_name"), case.get("cust_id"), default):
        if raw is None:
            continue
        cc = _normalize_customer_code(str(raw))
        if cc:
            return cc
    raise ValueError(
        "Cannot derive customer_code: set tenant_name on case or STELLAR_DEFAULT_CUSTOMER_CODE in .env"
    )


def _normalize_customer_code(raw: str) -> str:
    s = raw.strip().upper()
    if not s:
        return ""
    # tenant_name like JJNET; cust_id may be a long hex — take last 16 alnum or map via alias
    if _CUSTOMER_CODE_RE.match(s):
        return s
    alnum = re.sub(r"[^A-Z0-9]", "", s)
    if 2 <= len(alnum) <= 16:
        return alnum
    if len(alnum) > 16:
        return alnum[:16]
    return ""
