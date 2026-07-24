"""Tests for Stellar email ↔ Jira accountId assignee resolution."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import JiraSettings
from app.jira.client import JiraClient
from app.stellar.jira_assignee_update import apply_stellar_assignee_to_jira, jira_assignee_email
from app.stellar.user_map import (
    StellarJiraUserMap,
    load_stellar_jira_user_map,
    pick_account_id_from_search,
)


class TestPickAccountIdFromSearch(unittest.TestCase):
    def test_single_result_without_email_address(self) -> None:
        users = [{"accountId": "acc-1", "displayName": "arron"}]
        self.assertEqual(
            pick_account_id_from_search("arron.liao@jjnet.com.tw", users),
            "acc-1",
        )

    def test_display_name_matches_local_part(self) -> None:
        users = [
            {"accountId": "acc-1", "displayName": "arron"},
            {"accountId": "acc-2", "displayName": "bob"},
        ]
        self.assertEqual(
            pick_account_id_from_search("arron.liao@example.com", users),
            "acc-1",
        )


class TestJiraAssigneeEmail(unittest.TestCase):
    def test_uses_account_id_map_when_api_hides_email(self) -> None:
        user_map = StellarJiraUserMap(
            email_to_account_id={"a@example.com": "acc-1"},
            account_id_to_email={"acc-1": "a@example.com"},
        )
        fields = {"assignee": {"accountId": "acc-1", "displayName": "arron"}}
        self.assertEqual(jira_assignee_email(fields, user_map=user_map), "a@example.com")


class TestApplyStellarAssigneeToJira(unittest.IsolatedAsyncioTestCase):
    async def test_matches_by_account_id_when_jira_hides_email(self) -> None:
        jira = AsyncMock()
        jira.get_issue = AsyncMock(
            return_value={
                "fields": {
                    "assignee": {
                        "accountId": "acc-1",
                        "displayName": "arron",
                    }
                }
            }
        )
        jira.find_user_account_id_by_email = AsyncMock(return_value="acc-1")
        user_map = StellarJiraUserMap(
            email_to_account_id={"arron.liao@jjnet.com.tw": "acc-1"},
            account_id_to_email={"acc-1": "arron.liao@jjnet.com.tw"},
        )
        out = await apply_stellar_assignee_to_jira(
            jira=jira,
            issue_key="AIXSOC-1",
            case={"assignee_name": "arron.liao@jjnet.com.tw"},
            user_map=user_map,
        )
        self.assertTrue(out.get("skipped"))
        self.assertEqual(out.get("reason"), "already_in_sync")
        jira.update_issue.assert_not_awaited()

    async def test_updates_jira_when_account_differs(self) -> None:
        jira = AsyncMock()
        jira.get_issue = AsyncMock(return_value={"fields": {"assignee": None}})
        jira.find_user_account_id_by_email = AsyncMock(return_value="acc-1")
        jira.update_issue = AsyncMock()
        user_map = StellarJiraUserMap(
            email_to_account_id={"arron.liao@jjnet.com.tw": "acc-1"},
            account_id_to_email={"acc-1": "arron.liao@jjnet.com.tw"},
        )
        out = await apply_stellar_assignee_to_jira(
            jira=jira,
            issue_key="AIXSOC-1",
            case={"assignee_name": "arron.liao@jjnet.com.tw"},
            user_map=user_map,
        )
        self.assertTrue(out.get("updated"))
        jira.update_issue.assert_awaited_once_with(
            "AIXSOC-1",
            {"assignee": {"accountId": "acc-1"}},
        )


class TestFindUserAccountIdByEmail(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_single_search_result_fallback(self) -> None:
        j = JiraSettings.model_construct(
            jira_base_url="https://example.atlassian.net",
            jira_user_email="u@example.com",
            jira_api_token="token",
        )
        client = JiraClient(j)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"accountId": "acc-arron", "displayName": "arron"},
        ]
        with patch.object(client, "_client") as mock_client_factory:
            mock_http = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_client_factory.return_value = mock_http
            result = await client.find_user_account_id_by_email("arron.liao@jjnet.com.tw")
        self.assertEqual(result, "acc-arron")


if __name__ == "__main__":
    unittest.main()
