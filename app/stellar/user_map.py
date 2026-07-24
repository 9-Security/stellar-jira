"""Stellar assignee email ↔ Jira accountId mapping (when Jira API hides emails)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT = _REPO / "config" / "stellar_jira_user_map.example.json"


@dataclass(frozen=True)
class StellarJiraUserMap:
    email_to_account_id: dict[str, str]
    account_id_to_email: dict[str, str]


def load_stellar_jira_user_map(path: Path | None = None) -> StellarJiraUserMap:
    p = path or _DEFAULT
    if not p.is_file():
        return StellarJiraUserMap(email_to_account_id={}, account_id_to_email={})
    data = json.loads(p.read_text(encoding="utf-8"))
    e2a = data.get("email_to_account_id") if isinstance(data.get("email_to_account_id"), dict) else {}
    a2e = data.get("account_id_to_email") if isinstance(data.get("account_id_to_email"), dict) else {}
    email_map = {str(k).strip().lower(): str(v).strip() for k, v in e2a.items() if k and v}
    account_map = {str(k).strip(): str(v).strip().lower() for k, v in a2e.items() if k and v}
    for email, aid in email_map.items():
        account_map.setdefault(aid, email)
    return StellarJiraUserMap(email_to_account_id=email_map, account_id_to_email=account_map)


def account_id_for_email(email: str | None, user_map: StellarJiraUserMap) -> str | None:
    if not email or "@" not in str(email):
        return None
    return user_map.email_to_account_id.get(str(email).strip().lower())


def email_for_account_id(account_id: str | None, user_map: StellarJiraUserMap) -> str | None:
    if not account_id or not str(account_id).strip():
        return None
    return user_map.account_id_to_email.get(str(account_id).strip())


def pick_account_id_from_search(
    email: str,
    users: list[dict[str, Any]],
) -> str | None:
    """
  Resolve accountId from ``/user/search`` when ``emailAddress`` is omitted (common on Cloud).
    """
    needle = str(email or "").strip()
    if not needle or "@" not in needle:
        return None
    low = needle.lower()
    local = low.split("@", 1)[0]

    for user in users:
        if not isinstance(user, dict):
            continue
        if str(user.get("emailAddress") or "").strip().lower() == low:
            aid = user.get("accountId")
            if aid and str(aid).strip():
                return str(aid).strip()

    if len(users) == 1:
        only = users[0]
        if isinstance(only, dict):
            aid = only.get("accountId")
            if aid and str(aid).strip():
                return str(aid).strip()

    for user in users:
        if not isinstance(user, dict):
            continue
        dn = str(user.get("displayName") or "").strip().lower()
        if not dn:
            continue
        if dn == local or local.startswith(f"{dn}.") or dn == local.split(".")[0]:
            aid = user.get("accountId")
            if aid and str(aid).strip():
                return str(aid).strip()
    return None
