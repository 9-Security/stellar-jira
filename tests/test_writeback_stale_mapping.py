"""Tests for removing stale case↔Jira mappings on writeback Jira 404."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.jira.client import JiraAPIError
from app.stellar.writeback import apply_jira_to_stellar_writeback
from app.stellar_sync.writeback_runner import run_jira_to_stellar_writeback_cycle
from app.sync.state import SyncState


class TestWritebackStaleMapping(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "state.sqlite"
        self.state = SyncState(self.db_path)
        self.state.init(legacy_source_id="stellar")
        self.state.record("stellar", "case-gone", "AIXSOC-11")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_apply_writeback_removes_mapping_on_jira_404(self) -> None:
        settings = type(
            "St",
            (),
            {
                "stellar_base_url": "https://stellar.example",
                "stellar_api_key": "key",
                "stellar_poll_source_id": "stellar",
                "stellar_sync_state_db": str(self.db_path),
                "stellar_jira_field_map_path": "config/stellar_jira_fields.json",
                "stellar_resolution_tag_map_path": "config/stellar_resolution_tags.json",
                "stellar_jira_severity_field": None,
                "stellar_jira_status_field": None,
                "stellar_jira_resolution_tag_field": None,
                "stellar_timeout_seconds": 30.0,
                "stellar_tls_verify": True,
                "stellar_tenant_id": None,
            },
        )()
        jira_settings = type(
            "Js",
            (),
            {
                "jira_base_url": "https://jira.example",
                "jira_user_email": "u@example.com",
                "jira_api_token": "token",
            },
        )()

        with patch("app.stellar.writeback.get_stellar_settings", return_value=settings):
            with patch("app.stellar.writeback.get_jira_settings", return_value=jira_settings):
                with patch("app.stellar.writeback.load_stellar_jira_field_map", return_value={}):
                    with patch("app.stellar.writeback.load_resolution_tag_map") as tag_map:
                        tag_map.return_value.jira_field = "customfield_1"
                        with patch("app.stellar.writeback.JiraClient") as jira_cls:
                            jira = jira_cls.return_value
                            jira.get_issue = AsyncMock(
                                side_effect=JiraAPIError(
                                    "Jira HTTP 404 fetching issue AIXSOC-11",
                                    status_code=404,
                                )
                            )
                            result = await apply_jira_to_stellar_writeback(
                                issue_key="AIXSOC-11",
                                stellar_case_id="case-gone",
                                sync_fields=True,
                                st=settings,
                                jira_s=jira_settings,
                            )

        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("skipped"))
        self.assertTrue(result.get("stale_mapping_removed"))
        self.assertEqual(result.get("reason"), "jira_issue_gone")
        self.assertIsNone(self.state.get_jira_key("stellar", "case-gone"))

    async def test_writeback_cycle_skips_stale_mapping_without_error(self) -> None:
        stellar_settings = type(
            "St",
            (),
            {
                "stellar_poll_source_id": "stellar",
                "stellar_sync_state_db": str(self.db_path),
                "stellar_writeback_max_issues_per_cycle": 100,
            },
        )()

        async def fake_apply(*, issue_key: str, stellar_case_id: str | None = None, **kwargs):
            if issue_key == "AIXSOC-11":
                self.state.remove_incident_link("stellar", stellar_case_id or "")
                return {
                    "ok": True,
                    "skipped": True,
                    "issue_key": issue_key,
                    "stellar_case_id": stellar_case_id,
                    "reason": "jira_issue_gone",
                    "stale_mapping_removed": True,
                }
            return {"ok": True, "fields": {"skipped": True}}

        with patch("app.stellar_sync.writeback_runner.get_stellar_settings", return_value=stellar_settings):
            with patch(
                "app.stellar_sync.writeback_runner.apply_jira_to_stellar_writeback",
                new=AsyncMock(side_effect=fake_apply),
            ):
                out = await run_jira_to_stellar_writeback_cycle()

        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("errors"), [])
        self.assertEqual(out.get("skipped"), 1)


if __name__ == "__main__":
    unittest.main()
