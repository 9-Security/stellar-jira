"""Tests for Stellar duty-platform sync (mirror + limited writeback)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.stellar.writeback import (
    _filter_writeback_desired,
    _wb_jira_workflow_meta_key,
    apply_jira_workflow_change_guard,
    apply_stellar_newer_field_guard,
    build_stellar_update_body,
    extract_writeback_from_jira_fields,
)
from app.sync.state import SyncState


class TestDutyPlatformWriteback(unittest.TestCase):
    def test_writeback_strips_status_assignee_when_disabled(self) -> None:
        st = SimpleNamespace(
            stellar_jira_master_after_link=False,
            stellar_writeback_sync_status=False,
            stellar_writeback_sync_assignee=False,
            stellar_writeback_sync_severity=False,
        )
        fields = {
            "status": {"name": "In Progress"},
            "customfield_10061": {"value": "In Progress"},
            "assignee": {"emailAddress": "soc@example.com"},
            "customfield_10057": {"value": "High"},
        }
        desired = extract_writeback_from_jira_fields(
            fields,
            severity_field_id="customfield_10057",
            status_field_id="customfield_10061",
        )
        _filter_writeback_desired(st, desired)
        body = build_stellar_update_body(desired, {"status": "New", "severity": "Medium"})
        self.assertNotIn("status", body)
        self.assertNotIn("assignee", body)
        self.assertNotIn("severity", body)

    def test_jira_master_mode_still_allows_status_writeback(self) -> None:
        st = SimpleNamespace(
            stellar_jira_master_after_link=True,
            stellar_writeback_sync_status=False,
            stellar_writeback_sync_assignee=False,
            stellar_writeback_sync_severity=False,
        )
        fields = {
            "status": {"name": "Resolved"},
            "customfield_10061": {"value": "Resolved"},
        }
        desired = extract_writeback_from_jira_fields(
            fields,
            severity_field_id="customfield_10057",
            status_field_id="customfield_10061",
            prefer_workflow=True,
        )
        _filter_writeback_desired(st, desired)
        body = build_stellar_update_body(desired, {"status": "New"})
        self.assertEqual(body.get("status"), "Resolved")

    def test_stellar_newer_skips_nonterminal_jira_status(self) -> None:
        """Workflow-unchanged path: status already cleared before newer-guard."""
        st = SimpleNamespace(
            stellar_jira_master_after_link=False,
            stellar_writeback_sync_status=True,
            stellar_writeback_sync_assignee=False,
            stellar_writeback_sync_severity=False,
        )
        desired: dict = {"status": None, "assignee": None, "severity": None}
        flags = {"status": True, "assignee": False, "severity": False}
        result: dict = {}
        apply_stellar_newer_field_guard(
            st=st,
            desired=desired,
            jira_fields={"status": {"name": "Open"}},
            flags=flags,
            result=result,
        )
        self.assertIsNone(desired.get("status"))
        self.assertEqual(
            result.get("writeback_deferred"),
            "stellar_modified_newer_than_jira; mirror/inbound will push Stellar→Jira",
        )

    def test_stellar_newer_keeps_terminal_jira_status(self) -> None:
        st = SimpleNamespace(
            stellar_jira_master_after_link=False,
            stellar_writeback_sync_status=True,
            stellar_writeback_sync_assignee=False,
            stellar_writeback_sync_severity=False,
        )
        # Terminal status already admitted by workflow-change guard.
        desired: dict = {"status": "Resolved", "assignee": None, "severity": None}
        flags = {"status": True, "assignee": False, "severity": False}
        result: dict = {}
        apply_stellar_newer_field_guard(
            st=st,
            desired=desired,
            jira_fields={"status": {"name": "Resolved"}},
            flags=flags,
            result=result,
        )
        self.assertEqual(desired.get("status"), "Resolved")
        self.assertTrue(result.get("writeback_despite_stellar_newer"))
        self.assertTrue(result.get("writeback_terminal_status_override"))

    def test_workflow_unchanged_skips_status_despite_jira_updated(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            state = SyncState(Path(tmp.name) / "s.sqlite")
            state.init(legacy_source_id="stellar")
            state.set_meta(_wb_jira_workflow_meta_key("AIXSOC-50"), "Open")
            desired: dict = {"status": "New", "assignee": None}
            result: dict = {}
            apply_jira_workflow_change_guard(
                state=state,
                issue_key="AIXSOC-50",
                jira_fields={"status": {"name": "Open"}},
                desired=desired,
                result=result,
                dry_run=False,
            )
            self.assertIsNone(desired.get("status"))
            self.assertEqual(result.get("status_writeback_skipped"), "jira_workflow_unchanged")
        finally:
            tmp.cleanup()

    def test_workflow_change_keeps_status(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            state = SyncState(Path(tmp.name) / "s.sqlite")
            state.init(legacy_source_id="stellar")
            state.set_meta(_wb_jira_workflow_meta_key("AIXSOC-50"), "Open")
            desired: dict = {"status": "In Progress", "assignee": None}
            result: dict = {}
            apply_jira_workflow_change_guard(
                state=state,
                issue_key="AIXSOC-50",
                jira_fields={"status": {"name": "In Progress"}},
                desired=desired,
                result=result,
                dry_run=False,
            )
            self.assertEqual(desired.get("status"), "In Progress")
            self.assertEqual(
                state.get_meta(_wb_jira_workflow_meta_key("AIXSOC-50")),
                "In Progress",
            )
        finally:
            tmp.cleanup()


class TestMirrorRunner(unittest.IsolatedAsyncioTestCase):
    async def test_mirror_cycle_updates_linked_ticket(self) -> None:
        from app.stellar_sync import mirror_runner

        settings = SimpleNamespace(
            stellar_poll_source_id="stellar",
            stellar_sync_state_db="data/stellar_sync_state.sqlite",
            stellar_mirror_max_issues_per_cycle=100,
            stellar_mirror_case_activity_to_jira=False,
            stellar_base_url="https://stellar.example",
            stellar_api_key="key",
            stellar_timeout_seconds=30.0,
            stellar_tls_verify=True,
            stellar_tenant_id=None,
            stellar_sync_stellar_to_jira_status=True,
            stellar_sync_stellar_to_jira_assignee=False,
            stellar_sync_jira_workflow_status=True,
            stellar_sync_jira_custom_status=True,
            stellar_jira_status_field="customfield_10061",
        )

        with patch.object(mirror_runner, "get_stellar_settings", return_value=settings):
            with patch.object(mirror_runner, "get_jira_settings", return_value=SimpleNamespace()):
                with patch.object(mirror_runner, "SyncState") as mock_state_cls:
                    state = mock_state_cls.return_value
                    state.list_linked_jira_keys.return_value = [("case1", "AIXSOC-1")]

                    mock_client = AsyncMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.get_case = AsyncMock(return_value={"data": {}})
                    mock_client.extract_case_one.return_value = {
                        "_id": "case1",
                        "status": "Resolved",
                    }

                    mock_jira = AsyncMock()
                    mock_jira.__aenter__ = AsyncMock(return_value=mock_jira)
                    mock_jira.__aexit__ = AsyncMock(return_value=None)

                    with patch.object(mirror_runner, "StellarClient", return_value=mock_client):
                        with patch.object(mirror_runner, "JiraClient", return_value=mock_jira):
                            with patch.object(
                                mirror_runner,
                                "mirror_stellar_case_to_jira",
                                new_callable=AsyncMock,
                                return_value={"ok": True, "updated": True},
                            ) as mirror_fn:
                                out = await mirror_runner.run_stellar_to_jira_mirror_cycle(dry_run=False)

        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("updated"), 1)
        mirror_fn.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
