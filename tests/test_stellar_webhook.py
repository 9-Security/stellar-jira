"""Tests for Jira→Stellar webhook auth and HTTP responses."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.config import StellarSettings
from app.main import app


class TestStellarWebhookRoute(unittest.TestCase):
    def test_rejects_when_token_not_configured(self) -> None:
        settings = StellarSettings(
            stellar_webhook_token=None,
            sync_api_token=None,
            stellar_sync_state_db="data/test_stellar_sync_state.sqlite",
        )
        with patch("app.routers.stellar_webhook.get_stellar_settings", return_value=settings):
            client = TestClient(app)
            resp = client.post(
                "/v1/webhooks/jira-stellar",
                json={"issueKey": "AIXSOC-1"},
            )
        self.assertEqual(resp.status_code, 503)

    def test_rejects_invalid_token(self) -> None:
        settings = StellarSettings(
            stellar_webhook_token="secret-token",
            stellar_sync_state_db="data/test_stellar_sync_state.sqlite",
        )
        with patch("app.routers.stellar_webhook.get_stellar_settings", return_value=settings):
            client = TestClient(app)
            resp = client.post(
                "/v1/webhooks/jira-stellar",
                json={"issueKey": "AIXSOC-1"},
                headers={"X-Stellar-Webhook-Token": "wrong"},
            )
        self.assertEqual(resp.status_code, 403)

    def test_writeback_failure_returns_4xx(self) -> None:
        settings = StellarSettings(
            stellar_webhook_token="secret-token",
            stellar_sync_state_db="data/test_stellar_sync_state.sqlite",
        )
        with patch("app.routers.stellar_webhook.get_stellar_settings", return_value=settings):
            with patch(
                "app.routers.stellar_webhook.apply_jira_to_stellar_writeback",
                new=AsyncMock(
                    return_value={
                        "ok": False,
                        "issue_key": "AIXSOC-1",
                        "error": "stellar_case_id not found",
                    }
                ),
            ):
                with patch("app.routers.stellar_webhook.sync_process_lock"):
                    client = TestClient(app)
                    resp = client.post(
                        "/v1/webhooks/jira-stellar",
                        json={"issueKey": "AIXSOC-1"},
                        headers={"X-Stellar-Webhook-Token": "secret-token"},
                    )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.json().get("ok"))

    def test_writeback_success_returns_200(self) -> None:
        settings = StellarSettings(
            stellar_webhook_token="secret-token",
            stellar_sync_state_db="data/test_stellar_sync_state.sqlite",
        )
        with patch("app.routers.stellar_webhook.get_stellar_settings", return_value=settings):
            with patch(
                "app.routers.stellar_webhook.apply_jira_to_stellar_writeback",
                new=AsyncMock(return_value={"ok": True, "issue_key": "AIXSOC-1"}),
            ):
                with patch("app.routers.stellar_webhook.sync_process_lock"):
                    client = TestClient(app)
                    resp = client.post(
                        "/v1/webhooks/jira-stellar",
                        json={"issueKey": "AIXSOC-1"},
                        headers={"X-Stellar-Webhook-Token": "secret-token"},
                    )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))


if __name__ == "__main__":
    unittest.main()
