"""Repeatable Stellar→Jira sync: logging, graceful shutdown, optional fixed interval."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from typing import Any

from app.config import get_stellar_settings
from app.stellar.http_errors import inbound_stellar_unreachable
from app.stellar_sync.mirror_runner import run_stellar_to_jira_mirror_cycle
from app.stellar_sync.runner import run_stellar_to_jira_sync
from app.stellar_sync.writeback_runner import run_jira_to_stellar_writeback_cycle

logger = logging.getLogger("ticket_api.stellar_automation")

_ERR_BODY_LOG_MAX = 4000


def _log_sync_errors(errors: Any) -> None:
    if not isinstance(errors, list) or not errors:
        return
    for raw in errors:
        if not isinstance(raw, dict):
            logger.warning("stellar sync error (non-dict): %s", raw)
            continue
        msg = raw.get("error") or raw.get("detail") or raw.get("scope") or "unknown"
        logger.warning(
            "stellar sync error source_id=%s case_id=%s http_status=%s error_type=%s: %s",
            raw.get("source_id"),
            raw.get("case_id"),
            raw.get("http_status"),
            raw.get("error_type"),
            msg,
        )
        body = raw.get("body")
        if body is not None:
            try:
                text = json.dumps(body, default=str)
            except TypeError:
                text = str(body)
            if len(text) > _ERR_BODY_LOG_MAX:
                text = text[:_ERR_BODY_LOG_MAX] + "…(truncated)"
            logger.warning("stellar sync error response body: %s", text)


def setup_stellar_automation_logging(*, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _interruptible_sleep(seconds: float, stop: asyncio.Event) -> None:
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        chunk = min(remaining, 1.0)
        try:
            await asyncio.wait_for(stop.wait(), timeout=chunk)
            return
        except asyncio.TimeoutError:
            pass


async def run_stellar_automation_service(*, interval_seconds: int | None, dry_run: bool) -> int:
    setup_stellar_automation_logging()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    exit_code = 0
    first = True
    while not stop.is_set():
        if not first and interval_seconds is not None and interval_seconds > 0:
            logger.info("stellar sync sleeping %s s until next cycle", interval_seconds)
            await _interruptible_sleep(float(interval_seconds), stop)
            if stop.is_set():
                break
        first = False

        get_stellar_settings.cache_clear()
        st = get_stellar_settings()
        writeback_on = bool(st.stellar_automation_jira_writeback)
        mirror_on = bool(st.stellar_automation_jira_mirror)
        mirror_full_scan = bool(st.stellar_mirror_full_scan)

        logger.info(
            "stellar automation cycle start dry_run=%s inbound=1 mirror_poll=%s mirror_full_scan=%s writeback=%s",
            dry_run,
            mirror_on and st.stellar_mirror_on_poll,
            mirror_full_scan,
            writeback_on,
        )
        try:
            out: dict[str, Any] = await run_stellar_to_jira_sync(dry_run=dry_run)
        except ValueError as e:
            logger.error("stellar configuration error: %s", e)
            return 2
        except Exception:
            logger.exception("stellar inbound sync failed with an unexpected error")
            exit_code = 1
            if interval_seconds is None or interval_seconds <= 0:
                break
            continue

        if not out.get("ok"):
            exit_code = 1
        err_n = len(out.get("errors") or [])
        logger.info(
            "stellar inbound done ok=%s fetched=%s created=%s status_updated=%s assignee_updated=%s activity_posted=%s skipped=%s errors=%s",
            out.get("ok"),
            out.get("fetched"),
            len(out.get("created") or []),
            len(out.get("status_updated") or []),
            len(out.get("assignee_updated") or []),
            len(out.get("activity_posted") or []),
            out.get("skipped_already_synced"),
            err_n,
        )
        if err_n:
            _log_sync_errors(out.get("errors"))

        if mirror_full_scan:
            if inbound_stellar_unreachable(out):
                logger.warning(
                    "stellar mirror skipped: inbound Stellar poll failed (error_type=%s)",
                    out.get("error_type"),
                )
            else:
                try:
                    mir: dict[str, Any] = await run_stellar_to_jira_mirror_cycle(dry_run=dry_run)
                except Exception:
                    logger.exception("stellar jira mirror cycle failed")
                    exit_code = 1
                    mir = {"ok": False, "errors": [{"scope": "mirror", "error": "unexpected"}]}
                if not mir.get("ok"):
                    exit_code = 1
                mir_err = len(mir.get("errors") or [])
                logger.info(
                    "stellar mirror done ok=%s total=%s updated=%s activity_posted=%s skipped=%s errors=%s",
                    mir.get("ok"),
                    mir.get("total"),
                    mir.get("updated"),
                    mir.get("activity_posted"),
                    mir.get("skipped"),
                    mir_err,
                )
                for raw in mir.get("errors") or []:
                    if isinstance(raw, dict):
                        logger.warning(
                            "stellar mirror error jira_key=%s case_id=%s: %s",
                            raw.get("jira_key"),
                            raw.get("case_id"),
                            raw.get("error"),
                        )

        if writeback_on:
            if inbound_stellar_unreachable(out):
                logger.warning(
                    "stellar writeback skipped: inbound Stellar poll failed (error_type=%s)",
                    out.get("error_type"),
                )
            else:
                try:
                    wb: dict[str, Any] = await run_jira_to_stellar_writeback_cycle(dry_run=dry_run)
                except Exception:
                    logger.exception("stellar jira writeback cycle failed")
                    exit_code = 1
                    wb = {"ok": False, "errors": [{"scope": "writeback", "error": "unexpected"}]}
                if not wb.get("ok"):
                    exit_code = 1
                wb_err = len(wb.get("errors") or [])
                logger.info(
                    "stellar writeback done ok=%s total=%s updated=%s skipped=%s unchanged=%s errors=%s",
                    wb.get("ok"),
                    wb.get("total"),
                    wb.get("updated"),
                    wb.get("skipped"),
                    wb.get("skipped_unchanged"),
                    wb_err,
                )
                for raw in wb.get("errors") or []:
                    if isinstance(raw, dict):
                        logger.warning(
                            "stellar writeback error jira_key=%s case_id=%s: %s",
                            raw.get("jira_key"),
                            raw.get("case_id"),
                            raw.get("error"),
                        )

        if interval_seconds is None or interval_seconds <= 0:
            break

    if stop.is_set():
        logger.info("stellar shutdown signal received, exiting")
        return 0
    return exit_code
