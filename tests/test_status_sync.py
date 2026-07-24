"""Tests for Stellar ↔ Jira status sync (workflow + 事件狀態)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.stellar.jira_status_update import apply_stellar_status_to_jira
from app.stellar.status_sync import (
    needs_jira_custom_status_update,
    needs_jira_workflow_status_update,
    stellar_status_from_jira_fields,
)
from app.stellar.writeback import extract_writeback_from_jira_fields


class TestStellarStatusFromJiraFields(unittest.TestCase):
    def test_workflow_only_when_custom_disabled(self) -> None:
        fields = {
            "status": {"name": "In Progress"},
            "customfield_10061": {"value": "New"},
        }
        got = stellar_status_from_jira_fields(
            fields,
            status_field_id="customfield_10061",
            sync_custom_status=False,
        )
        self.assertEqual(got, "In Progress")

    def test_custom_only_when_workflow_missing(self) -> None:
        fields = {"customfield_10061": {"value": "Escalated"}}
        got = stellar_status_from_jira_fields(
            fields,
            status_field_id="customfield_10061",
            sync_custom_status=True,
        )
        self.assertEqual(got, "Escalated")

    def test_prefer_workflow_on_conflict(self) -> None:
        fields = {
            "status": {"name": "In Progress"},
            "customfield_10061": {"value": "New"},
        }
        got = stellar_status_from_jira_fields(
            fields,
            status_field_id="customfield_10061",
            prefer_workflow=True,
            sync_custom_status=True,
        )
        self.assertEqual(got, "In Progress")

    def test_prefer_custom_on_conflict(self) -> None:
        fields = {
            "status": {"name": "In Progress"},
            "customfield_10061": {"value": "New"},
        }
        got = stellar_status_from_jira_fields(
            fields,
            status_field_id="customfield_10061",
            prefer_workflow=False,
            sync_custom_status=True,
        )
        self.assertEqual(got, "New")


class TestNeedsJiraStatusUpdate(unittest.TestCase):
    def test_custom_needs_update_when_stale(self) -> None:
        fields = {"customfield_10061": {"value": "New"}}
        self.assertTrue(
            needs_jira_custom_status_update(
                fields,
                stellar_status="Resolved",
                status_field_id="customfield_10061",
            )
        )

    def test_workflow_needs_update_when_mapped_status_differs(self) -> None:
        fields = {"status": {"name": "Open"}}
        self.assertTrue(needs_jira_workflow_status_update(fields, stellar_status="In Progress"))


class TestExtractWritebackStatus(unittest.TestCase):
    def test_writeback_uses_custom_when_prefer_custom(self) -> None:
        fields = {
            "status": {"name": "In Progress"},
            "customfield_10061": {"value": "New"},
            "customfield_10057": {"value": "High"},
        }
        out = extract_writeback_from_jira_fields(
            fields,
            severity_field_id="customfield_10057",
            status_field_id="customfield_10061",
            prefer_workflow=False,
            sync_custom_status=True,
        )
        self.assertEqual(out["status"], "New")


class TestApplyStellarStatusToJira(unittest.IsolatedAsyncioTestCase):
    async def test_updates_custom_when_workflow_transition_unavailable(self) -> None:
        jira = AsyncMock()
        jira.get_issue = AsyncMock(
            return_value={
                "fields": {
                    "status": {"name": "In Progress"},
                    "customfield_10061": {"value": "New"},
                }
            }
        )
        jira.get_transitions = AsyncMock(return_value=[])
        jira.update_issue = AsyncMock()

        settings = type(
            "S",
            (),
            {
                "stellar_sync_jira_workflow_status": True,
                "stellar_sync_jira_custom_status": True,
                "stellar_jira_status_field": "customfield_10061",
                "stellar_writeback_sync_status": True,
                "stellar_jira_master_after_link": False,
            },
        )()

        out = await apply_stellar_status_to_jira(
            jira=jira,
            issue_key="AIXSOC-99",
            stellar_status="Resolved",
            st=settings,
            dry_run=False,
        )

        self.assertTrue(out.get("updated"))
        jira.update_issue.assert_awaited_once_with(
            "AIXSOC-99",
            {"customfield_10061": {"value": "Resolved"}},
        )

    async def test_dry_run_reports_both_targets(self) -> None:
        jira = AsyncMock()
        jira.get_issue = AsyncMock(
            return_value={
                "fields": {
                    "status": {"name": "Open"},
                    "customfield_10061": {"value": "New"},
                }
            }
        )

        settings = type(
            "S",
            (),
            {
                "stellar_sync_jira_workflow_status": True,
                "stellar_sync_jira_custom_status": True,
                "stellar_jira_status_field": "customfield_10061",
                "stellar_writeback_sync_status": True,
                "stellar_jira_master_after_link": False,
            },
        )()

        out = await apply_stellar_status_to_jira(
            jira=jira,
            issue_key="AIXSOC-99",
            stellar_status="In Progress",
            st=settings,
            dry_run=True,
        )

        self.assertTrue(out.get("dry_run"))
        actions = out.get("actions") or {}
        self.assertEqual(actions.get("workflow_target"), "In Progress")
        self.assertEqual(actions.get("custom_status_target"), "In Progress")

    async def test_skips_reopen_when_jira_terminal_and_writeback_owns(self) -> None:
        jira = AsyncMock()
        jira.get_issue = AsyncMock(
            return_value={
                "fields": {
                    "status": {"name": "Resolved"},
                    "customfield_10061": {"value": "Resolved"},
                }
            }
        )
        jira.get_transitions = AsyncMock()
        jira.update_issue = AsyncMock()

        settings = type(
            "S",
            (),
            {
                "stellar_sync_jira_workflow_status": True,
                "stellar_sync_jira_custom_status": True,
                "stellar_jira_status_field": "customfield_10061",
                "stellar_writeback_sync_status": True,
                "stellar_jira_master_after_link": False,
            },
        )()

        out = await apply_stellar_status_to_jira(
            jira=jira,
            issue_key="AIXSOC-48",
            stellar_status="In Progress",
            st=settings,
            dry_run=False,
        )

        self.assertTrue(out.get("skipped"))
        self.assertEqual(out.get("reason"), "jira_terminal_writeback_owns")
        jira.get_transitions.assert_not_awaited()
        jira.update_issue.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
