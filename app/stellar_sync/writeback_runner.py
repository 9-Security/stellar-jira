"""Poll linked Jira AIxSOC issues and push field changes to Stellar (batch)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import get_jira_settings, get_stellar_settings
from app.jira.client import JiraAPIError, JiraClient
from app.stellar.writeback import apply_jira_to_stellar_writeback
from app.sync.state import SyncState

REPO_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

_WB_JIRA_UPDATED_PREFIX = "wb_jira_updated:"
_JQL_KEY_CHUNK = 40


def _wb_jira_updated_meta_key(jira_key: str) -> str:
    return f"{_WB_JIRA_UPDATED_PREFIX}{str(jira_key or '').strip().upper()}"


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    n = max(1, int(size))
    for i in range(0, len(items), n):
        yield items[i : i + n]


async def fetch_jira_updated_by_key(
    jira: JiraClient,
    jira_keys: list[str],
    *,
    chunk_size: int = _JQL_KEY_CHUNK,
) -> dict[str, str]:
    """Return ``{JIRA_KEY: updated_iso}`` via batched JQL (fields=updated only)."""
    keys = [str(k or "").strip().upper() for k in jira_keys if str(k or "").strip()]
    out: dict[str, str] = {}
    for chunk in _chunks(keys, chunk_size):
        key_list = ", ".join(f'"{k}"' for k in chunk)
        jql = f"key in ({key_list})"
        issues = await jira.search_issues(jql, fields=["updated"], max_results=max(len(chunk), 1))
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            key = str(issue.get("key") or "").strip().upper()
            fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
            updated = str(fields.get("updated") or "").strip()
            if key and updated:
                out[key] = updated
    return out


def _persist_writeback_summary(state: SyncState, source_id: str, out: dict[str, Any]) -> None:
    sfx = f":{source_id}"
    state.set_meta("last_writeback_finished_at" + sfx, datetime.now(timezone.utc).isoformat())
    state.set_meta("last_writeback_ok" + sfx, "1" if out.get("ok") else "0")
    state.set_meta("last_writeback_total" + sfx, str(int(out.get("total") or 0)))
    state.set_meta("last_writeback_updated" + sfx, str(int(out.get("updated") or 0)))
    state.set_meta("last_writeback_skipped" + sfx, str(int(out.get("skipped") or 0)))
    state.set_meta("last_writeback_errors" + sfx, str(len(out.get("errors") or [])))
    state.set_meta(
        "last_writeback_unchanged" + sfx,
        str(int(out.get("skipped_unchanged") or 0)),
    )


async def run_jira_to_stellar_writeback_cycle(*, dry_run: bool = False) -> dict[str, Any]:
    """
    For each ``(case_id, jira_key)`` in stellar sync SQLite, read Jira fields and
    PUT Stellar case when assignee / status / severity / resolution tag differ.

    Issues whose Jira ``updated`` timestamp matches the last successful writeback
    check are skipped (no Stellar GET), so idle cycles stay cheap.
    """
    get_stellar_settings.cache_clear()
    get_jira_settings.cache_clear()
    st = get_stellar_settings()
    source_id = (st.stellar_poll_source_id or "stellar").strip() or "stellar"
    state_path = REPO_ROOT / st.stellar_sync_state_db
    state = SyncState(state_path)
    state.init(legacy_source_id=source_id)

    linked = state.list_linked_jira_keys(source_id)
    max_n = int(st.stellar_writeback_max_issues_per_cycle)
    if max_n > 0 and len(linked) > max_n:
        linked = linked[:max_n]

    updated = 0
    skipped = 0
    skipped_unchanged = 0
    errors: list[dict[str, Any]] = []
    per: list[dict[str, Any]] = []

    jira_updated: dict[str, str] = {}
    jira_s = get_jira_settings()
    if linked:
        try:
            async with JiraClient(jira_s) as jira:
                jira_updated = await fetch_jira_updated_by_key(
                    jira, [jk for _, jk in linked]
                )
        except (JiraAPIError, ValueError) as e:
            logger.warning("writeback Jira updated prefetch failed; full scan: %s", e)
            jira_updated = {}

    for case_id, jira_key in linked:
        t0 = time.monotonic()
        jk = str(jira_key or "").strip().upper()
        meta_key = _wb_jira_updated_meta_key(jk)
        cur_updated = jira_updated.get(jk)
        prev_updated = state.get_meta(meta_key)
        if cur_updated and prev_updated and cur_updated == prev_updated:
            skipped += 1
            skipped_unchanged += 1
            per.append(
                {
                    "jira_key": jk,
                    "case_id": case_id,
                    "ok": True,
                    "skipped": True,
                    "reason": "jira_unchanged",
                    "stale_mapping_removed": False,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                }
            )
            continue

        try:
            one = await apply_jira_to_stellar_writeback(
                issue_key=jk,
                stellar_case_id=case_id,
                dry_run=dry_run,
                sync_fields=True,
            )
        except Exception as e:
            logger.exception("writeback failed jira_key=%s case_id=%s", jk, case_id)
            errors.append({"jira_key": jk, "case_id": case_id, "error": str(e)})
            continue

        fields = one.get("fields") if isinstance(one.get("fields"), dict) else {}
        if not one.get("ok"):
            errors.append(
                {
                    "jira_key": jk,
                    "case_id": case_id,
                    "error": one.get("error"),
                    "http_status": one.get("http_status"),
                }
            )
        elif one.get("skipped") or fields.get("skipped") or one.get("stale_mapping_removed"):
            skipped += 1
            if not dry_run and cur_updated and not one.get("stale_mapping_removed"):
                state.set_meta(meta_key, cur_updated)
        elif dry_run and fields.get("would_update"):
            updated += 1
        elif fields.get("updated"):
            updated += 1
            if not dry_run and cur_updated:
                state.set_meta(meta_key, cur_updated)
        else:
            # Unexpected shape; still record watermark if Jira looked unchanged after apply.
            if not dry_run and cur_updated and one.get("ok"):
                state.set_meta(meta_key, cur_updated)

        per.append(
            {
                "jira_key": jk,
                "case_id": case_id,
                "ok": one.get("ok"),
                "skipped": bool(
                    one.get("skipped") or fields.get("skipped") or one.get("stale_mapping_removed")
                ),
                "reason": one.get("reason") or fields.get("reason"),
                "stale_mapping_removed": bool(one.get("stale_mapping_removed")),
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
        )

    out: dict[str, Any] = {
        "ok": not errors,
        "source_id": source_id,
        "dry_run": dry_run,
        "total": len(linked),
        "updated": updated,
        "skipped": skipped,
        "skipped_unchanged": skipped_unchanged,
        "errors": errors,
        "results": per,
    }
    _persist_writeback_summary(state, source_id, out)
    return out
