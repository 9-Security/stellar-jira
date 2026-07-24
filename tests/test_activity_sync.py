"""Tests for Stellar activity → Jira comment formatting."""

from __future__ import annotations

import unittest

from app.stellar.activity_sync import (
    activity_sync_key,
    format_activity_jira_comment,
    sort_activities_chronologically,
)


class TestFormatActivityJiraComment(unittest.TestCase):
    def test_comment_activity(self) -> None:
        text = format_activity_jira_comment(
            {
                "action": "add",
                "field": "comment",
                "to": "誤報",
                "user": "arron.liao@jjnet.com.tw",
                "timestamp": 1783564326843,
            },
            timezone_name="UTC",
        )
        self.assertIn("[Stellar Activity]", text or "")
        self.assertIn("誤報", text or "")

    def test_status_update_activity(self) -> None:
        text = format_activity_jira_comment(
            {
                "action": "update",
                "field": "status",
                "from": "New",
                "to": "In Progress",
                "user": "soc",
                "timestamp": 1783563218974,
            },
            timezone_name="UTC",
        )
        self.assertIn("status", text or "")
        self.assertIn("New", text or "")
        self.assertIn("In Progress", text or "")

    def test_skips_jira_echo_comment(self) -> None:
        text = format_activity_jira_comment(
            {
                "action": "add",
                "field": "comment",
                "to": "[Jira AIXSOC-1] analyst: hello",
                "user": "x",
                "timestamp": 1,
            }
        )
        self.assertIsNone(text)

    def test_stable_activity_key(self) -> None:
        act = {
            "action": "update",
            "field": "status",
            "from": "New",
            "to": "Resolved",
            "timestamp": 123,
            "user": "u1",
        }
        k1 = activity_sync_key("case1", act)
        k2 = activity_sync_key("case1", act)
        self.assertEqual(k1, k2)

    def test_sort_chronological(self) -> None:
        items = [{"timestamp": 200}, {"timestamp": 100}, {"timestamp": 300}]
        out = sort_activities_chronologically(items)
        self.assertEqual([x["timestamp"] for x in out], [100, 200, 300])


if __name__ == "__main__":
    unittest.main()
