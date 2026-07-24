"""Tests for Jira-as-master-after-link writeback policy."""

from __future__ import annotations

import unittest

from app.stellar.writeback import build_stellar_update_body, extract_writeback_from_jira_fields


class TestJiraMasterAfterLink(unittest.TestCase):
    def test_writeback_prefers_jira_workflow_when_fields_disagree(self) -> None:
        fields = {
            "status": {"name": "In Progress"},
            "customfield_10061": {"value": "New"},
            "assignee": {"emailAddress": "soc@example.com"},
        }
        desired = extract_writeback_from_jira_fields(
            fields,
            severity_field_id="customfield_10057",
            status_field_id="customfield_10061",
            prefer_workflow=True,
            sync_custom_status=True,
        )
        current = {"status": "New", "assignee_name": "Unassigned"}
        body = build_stellar_update_body(desired, current)
        self.assertEqual(body.get("status"), "In Progress")
        self.assertEqual(body.get("assignee"), "soc@example.com")

    def test_writeback_updates_stellar_even_when_stellar_modified_is_newer(self) -> None:
        """Jira-master mode: body should still be built from Jira (no caller-side clearing)."""
        fields = {
            "status": {"name": "Resolved"},
            "customfield_10061": {"value": "Resolved"},
            "updated": "2026-07-09T08:00:00.000+0800",
        }
        desired = extract_writeback_from_jira_fields(
            fields,
            severity_field_id="customfield_10057",
            status_field_id="customfield_10061",
            prefer_workflow=True,
            sync_custom_status=True,
        )
        current = {
            "status": "New",
            "modified_at": 1784000000000,
        }
        body = build_stellar_update_body(desired, current)
        self.assertEqual(body.get("status"), "Resolved")


if __name__ == "__main__":
    unittest.main()
