"""Incremental Jira→Stellar writeback (skip unchanged Jira updated timestamps)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.stellar_sync.writeback_runner import (
    _chunks,
    _wb_jira_updated_meta_key,
    fetch_jira_updated_by_key,
    run_jira_to_stellar_writeback_cycle,
)
from app.sync.state import SyncState


class TestWritebackIncrementalHelpers(unittest.TestCase):
    def test_meta_key_normalizes(self) -> None:
        self.assertEqual(_wb_jira_updated_meta_key("aixsoc-1"), "wb_jira_updated:AIXSOC-1")

    def test_chunks(self) -> None:
        self.assertEqual(list(_chunks(["a", "b", "c"], 2)), [["a", "b"], ["c"]])


class TestFetchJiraUpdatedByKey(unittest.IsolatedAsyncioTestCase):
    async def test_maps_updated_from_search(self) -> None:
        jira = AsyncMock()
        jira.search_issues = AsyncMock(
            return_value=[
                {"key": "AIXSOC-1", "fields": {"updated": "2026-07-13T01:00:00.000+0000"}},
                {"key": "AIXSOC-2", "fields": {"updated": "2026-07-13T02:00:00.000+0000"}},
            ]
        )
        out = await fetch_jira_updated_by_key(jira, ["aixsoc-1", "AIXSOC-2"])
        self.assertEqual(out["AIXSOC-1"], "2026-07-13T01:00:00.000+0000")
        self.assertEqual(out["AIXSOC-2"], "2026-07-13T02:00:00.000+0000")
        jira.search_issues.assert_awaited()


class TestWritebackCycleSkipUnchanged(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_jira_updated_matches_meta(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            state_path = Path(tmp.name) / "s.sqlite"
            state = SyncState(state_path)
            state.init(legacy_source_id="stellar")
            state.record("stellar", "case-1", "AIXSOC-1")
            state.set_meta(
                _wb_jira_updated_meta_key("AIXSOC-1"),
                "2026-07-13T01:00:00.000+0000",
            )

            settings = type(
                "S",
                (),
                {
                    "stellar_poll_source_id": "stellar",
                    "stellar_sync_state_db": str(state_path),
                    "stellar_writeback_max_issues_per_cycle": 100,
                },
            )()
            jira_settings = type("J", (), {})()

            mock_jira = AsyncMock()
            mock_jira.__aenter__ = AsyncMock(return_value=mock_jira)
            mock_jira.__aexit__ = AsyncMock(return_value=None)
            mock_jira.search_issues = AsyncMock(
                return_value=[
                    {
                        "key": "AIXSOC-1",
                        "fields": {"updated": "2026-07-13T01:00:00.000+0000"},
                    }
                ]
            )

            with (
                patch(
                    "app.stellar_sync.writeback_runner.get_stellar_settings",
                    return_value=settings,
                ),
                patch(
                    "app.stellar_sync.writeback_runner.get_jira_settings",
                    return_value=jira_settings,
                ),
                patch(
                    "app.stellar_sync.writeback_runner.JiraClient",
                    return_value=mock_jira,
                ),
                patch(
                    "app.stellar_sync.writeback_runner.apply_jira_to_stellar_writeback",
                    new_callable=AsyncMock,
                ) as apply_mock,
            ):
                out = await run_jira_to_stellar_writeback_cycle(dry_run=False)

            self.assertTrue(out["ok"])
            self.assertEqual(out["total"], 1)
            self.assertEqual(out["skipped_unchanged"], 1)
            self.assertEqual(out["skipped"], 1)
            apply_mock.assert_not_awaited()
        finally:
            tmp.cleanup()

    async def test_applies_when_jira_updated_changed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            state_path = Path(tmp.name) / "s.sqlite"
            state = SyncState(state_path)
            state.init(legacy_source_id="stellar")
            state.record("stellar", "case-1", "AIXSOC-1")
            state.set_meta(
                _wb_jira_updated_meta_key("AIXSOC-1"),
                "2026-07-13T01:00:00.000+0000",
            )

            settings = type(
                "S",
                (),
                {
                    "stellar_poll_source_id": "stellar",
                    "stellar_sync_state_db": str(state_path),
                    "stellar_writeback_max_issues_per_cycle": 100,
                },
            )()
            jira_settings = type("J", (), {})()

            mock_jira = AsyncMock()
            mock_jira.__aenter__ = AsyncMock(return_value=mock_jira)
            mock_jira.__aexit__ = AsyncMock(return_value=None)
            mock_jira.search_issues = AsyncMock(
                return_value=[
                    {
                        "key": "AIXSOC-1",
                        "fields": {"updated": "2026-07-13T02:00:00.000+0000"},
                    }
                ]
            )

            with (
                patch(
                    "app.stellar_sync.writeback_runner.get_stellar_settings",
                    return_value=settings,
                ),
                patch(
                    "app.stellar_sync.writeback_runner.get_jira_settings",
                    return_value=jira_settings,
                ),
                patch(
                    "app.stellar_sync.writeback_runner.JiraClient",
                    return_value=mock_jira,
                ),
                patch(
                    "app.stellar_sync.writeback_runner.apply_jira_to_stellar_writeback",
                    new_callable=AsyncMock,
                    return_value={
                        "ok": True,
                        "fields": {"skipped": True, "reason": "no_changes"},
                    },
                ) as apply_mock,
            ):
                out = await run_jira_to_stellar_writeback_cycle(dry_run=False)

            self.assertTrue(out["ok"])
            self.assertEqual(out["skipped_unchanged"], 0)
            apply_mock.assert_awaited_once()
            state2 = SyncState(state_path)
            self.assertEqual(
                state2.get_meta(_wb_jira_updated_meta_key("AIXSOC-1")),
                "2026-07-13T02:00:00.000+0000",
            )
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
