"""Shared watermark and SQLite meta helpers for Cortex / Stellar sync runners."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.sync.state import SyncState


def watermark_meta_key(source_id: str) -> str:
    return f"last_max_mod_ms:{source_id}"


def note_watermark_mod(watermark_mod_ms: int, modified_at_ms: int) -> int:
    if modified_at_ms > 0:
        return max(watermark_mod_ms, modified_at_ms)
    return watermark_mod_ms


def finalize_watermark_ms(
    watermark_mod_ms: int,
    *,
    failed_modified_at_ms: list[int],
    existing_watermark_ms: int,
) -> int:
    """
    Cap watermark so failed creates remain inside the poll window (modified_at >= wm - backoff).

    When this cycle only had failures, rewind an already-high stored watermark.
    """
    if not failed_modified_at_ms:
        return watermark_mod_ms
    cap = min(failed_modified_at_ms) - 1
    if cap <= 0:
        return watermark_mod_ms
    if watermark_mod_ms > 0:
        return min(watermark_mod_ms, cap)
    if existing_watermark_ms > cap:
        return cap
    return watermark_mod_ms


def persist_per_source_sync_meta(
    state: SyncState, source_id: str, *, dry_run: bool, skipped: int, out: dict[str, Any]
) -> None:
    sfx = f":{source_id}"
    wc = out.get("would_create")
    would_n = len(wc) if isinstance(wc, list) else 0
    created = out.get("created")
    created_n = len(created) if isinstance(created, list) else 0
    state.set_meta("last_sync_finished_at" + sfx, datetime.now(timezone.utc).isoformat())
    state.set_meta("last_sync_dry_run" + sfx, "1" if dry_run else "0")
    state.set_meta("last_sync_fetched" + sfx, str(int(out.get("fetched") or 0)))
    state.set_meta("last_sync_created_count" + sfx, str(created_n))
    state.set_meta("last_sync_would_create_count" + sfx, str(would_n))
    state.set_meta("last_sync_skipped" + sfx, str(skipped))
    state.set_meta("last_sync_ok" + sfx, "1" if out.get("ok") else "0")


def persist_aggregate_sync_meta(
    state: SyncState, *, dry_run: bool, skipped_total: int, out: dict[str, Any]
) -> None:
    wc = out.get("would_create")
    would_n = len(wc) if isinstance(wc, list) else 0
    created = out.get("created")
    created_n = len(created) if isinstance(created, list) else 0
    state.set_meta("last_sync_finished_at", datetime.now(timezone.utc).isoformat())
    state.set_meta("last_sync_dry_run", "1" if dry_run else "0")
    state.set_meta("last_sync_fetched", str(int(out.get("fetched") or 0)))
    state.set_meta("last_sync_created_count", str(created_n))
    state.set_meta("last_sync_would_create_count", str(would_n))
    state.set_meta("last_sync_skipped", str(skipped_total))
    state.set_meta("last_sync_ok", "1" if out.get("ok") else "0")


def append_truncation_error(
    out: dict[str, Any],
    *,
    source_id: str,
    scope: str,
    max_pages: int,
    page_size_env_hint: str,
) -> None:
    out["truncated"] = True
    out["ok"] = False
    out.setdefault("errors", []).append(
        {
            "source_id": source_id,
            "scope": scope,
            "error": (
                f"fetch truncated at {max_pages} pages; "
                f"increase {page_size_env_hint} or SYNC_MAX_PAGES / STELLAR_SYNC_MAX_PAGES and run again"
            ),
        }
    )
