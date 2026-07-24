from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from app.stellar.report_runner import fetch_mttr_minutes


class TestTenantMttr(unittest.IsolatedAsyncioTestCase):
    async def test_mttr_jql_is_scoped_by_tenant_label(self) -> None:
        settings = MagicMock()
        settings.jira_base_url = "https://example.atlassian.net"
        client = MagicMock()
        client.search_issues = AsyncMock(return_value=[])

        with patch("app.stellar.report_runner.get_jira_settings", return_value=settings):
            with patch("app.stellar.report_runner.JiraClient", return_value=client):
                result = await fetch_mttr_minutes(
                    project_key="AIXSOC",
                    start_d=date(2026, 7, 1),
                    end_d=date(2026, 7, 31),
                    tenant_label="tenant-jjnet",
                )

        self.assertEqual(result, "N/A")
        jql = client.search_issues.await_args.args[0]
        self.assertIn('labels = "tenant-jjnet"', jql)
        self.assertIn("project = AIXSOC", jql)


if __name__ == "__main__":
    unittest.main()
