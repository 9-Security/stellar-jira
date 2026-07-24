"""Tests for Jira client helpers (no network)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import JiraSettings
from app.jira.client import JiraClient, JiraAPIError, _jql_escape


class TestJqlEscape(unittest.TestCase):
    def test_escapes_quotes_and_backslashes(self) -> None:
        self.assertEqual(_jql_escape('foo"bar\\baz'), 'foo\\"bar\\\\baz')


class TestFindUserAccountIdByEmail(unittest.IsolatedAsyncioTestCase):
    async def test_exact_email_match_only(self) -> None:
        j = JiraSettings.model_construct(
            jira_base_url="https://example.atlassian.net",
            jira_user_email="u@example.com",
            jira_api_token="token",
        )
        client = JiraClient(j)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"accountId": "wrong-id", "emailAddress": "other@example.com"},
            {"accountId": "right-id", "emailAddress": "target@example.com"},
        ]
        with patch.object(client, "_client") as mock_client_factory:
            mock_http = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_client_factory.return_value = mock_http
            result = await client.find_user_account_id_by_email("target@example.com")
        self.assertEqual(result, "right-id")

    async def test_no_exact_match_returns_none(self) -> None:
        j = JiraSettings.model_construct(
            jira_base_url="https://example.atlassian.net",
            jira_user_email="u@example.com",
            jira_api_token="token",
        )
        client = JiraClient(j)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"accountId": "only-id", "emailAddress": "other@example.com", "displayName": "bob"},
            {"accountId": "two-id", "displayName": "alice"},
        ]
        with patch.object(client, "_client") as mock_client_factory:
            mock_http = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_client_factory.return_value = mock_http
            result = await client.find_user_account_id_by_email("target@example.com")
        self.assertIsNone(result)


class TestCreateIssueResilient(unittest.IsolatedAsyncioTestCase):
    async def test_retries_without_screen_restricted_fields(self) -> None:
        j = JiraSettings.model_construct(
            jira_base_url="https://example.atlassian.net",
            jira_user_email="u@example.com",
            jira_api_token="token",
        )
        client = JiraClient(j)
        fields = {
            "project": {"key": "AIXSOC"},
            "issuetype": {"id": "10092"},
            "summary": "test",
            "description": {"type": "doc", "version": 1, "content": []},
            "customfield_10057": {"value": "High"},
            "customfield_10061": {"value": "New"},
        }

        async def fake_create(payload: dict[str, Any]) -> dict[str, Any]:
            if "customfield_10057" in payload:
                raise JiraAPIError(
                    "Jira HTTP 400 creating issue",
                    status_code=400,
                    body={
                        "errors": {
                            "customfield_10057": "cannot be set",
                            "customfield_10061": "cannot be set",
                        }
                    },
                )
            return {"key": "AIXSOC-99", "id": "10099"}

        update_calls: list[dict[str, Any]] = []

        async def fake_update(issue_key: str, payload: dict[str, Any]) -> None:
            update_calls.append(payload)

        with patch.object(client, "create_issue", side_effect=fake_create):
            with patch.object(client, "update_issue", side_effect=fake_update):
                out = await client.create_issue_resilient(fields)

        self.assertEqual(out.get("key"), "AIXSOC-99")
        self.assertEqual(
            update_calls[0],
            {
                "customfield_10057": {"value": "High"},
                "customfield_10061": {"value": "New"},
            },
        )


if __name__ == "__main__":
    unittest.main()
