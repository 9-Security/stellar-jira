"""Tests for notify_ticket_created email/LINE channel behavior."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.config import NotifySettings
from app.notify.ticket_created import notify_ticket_created

_VALID_USER = "U" + "a" * 32


class TestNotifyTicketCreatedLine(unittest.IsolatedAsyncioTestCase):
    async def test_ai_fail_open_false_still_sends_line_when_email_disabled(self) -> None:
        settings = NotifySettings(
            soc_notify_enabled=False,
            line_notify_enabled=True,
            line_channel_access_token="line-token",
            line_notify_to=_VALID_USER,
            soc_notify_ai_enabled=True,
            soc_notify_ai_api_key="test-key",
            soc_notify_ai_fail_open=False,
        )
        stellar_case = {
            "_id": "case-1",
            "name": "Test Alert",
            "severity": "High",
        }
        ai_status = {"ok": False, "error": "groq failed"}

        with patch(
            "app.decision.ai_bridge.generate_ai_aligned_with_decision",
            new=AsyncMock(return_value=ai_status),
        ):
            with patch(
                "app.notify.ticket_created.send_line_notify",
                new=AsyncMock(return_value={"sent": True, "provider": "line", "recipients": [_VALID_USER]}),
            ) as line_send:
                result = await notify_ticket_created(
                    jira_key="AIXSOC-1",
                    case_id="XSOC-1",
                    summary="test",
                    customer_code="JJ",
                    source_id="stellar",
                    external_id="case-1",
                    platform="stellar",
                    stellar_case=stellar_case,
                    stellar_bundle={"case_id": "case-1", "case": stellar_case},
                    settings=settings,
                )

        self.assertTrue(result.get("sent"))
        self.assertTrue(result.get("line", {}).get("sent"))
        line_send.assert_awaited_once()

    async def test_ai_fail_open_false_blocks_email_only(self) -> None:
        settings = NotifySettings(
            soc_notify_enabled=True,
            line_notify_enabled=False,
            soc_notify_from="test@example.com",
            resend_api_key="re_test",
            soc_notify_to="soc@example.com",
            soc_notify_ai_enabled=True,
            soc_notify_ai_api_key="test-key",
            soc_notify_ai_fail_open=False,
        )
        stellar_case = {"_id": "case-1", "name": "Test Alert", "severity": "High"}
        ai_status = {"ok": False, "error": "groq failed"}

        with patch(
            "app.decision.ai_bridge.generate_ai_aligned_with_decision",
            new=AsyncMock(return_value=ai_status),
        ):
            with patch("app.notify.ticket_created.send_email", new=AsyncMock()) as email_send:
                result = await notify_ticket_created(
                    jira_key="AIXSOC-1",
                    case_id="XSOC-1",
                    summary="test",
                    customer_code="JJ",
                    source_id="stellar",
                    external_id="case-1",
                    platform="stellar",
                    stellar_case=stellar_case,
                    stellar_bundle={"case_id": "case-1", "case": stellar_case},
                    settings=settings,
                )

        self.assertFalse(result.get("sent"))
        self.assertIn("ai_failed", str(result.get("error") or ""))
        email_send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
