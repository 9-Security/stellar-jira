"""Tests for SOC notify email CC/BCC wiring."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.config import NotifySettings
from app.notify.resend_api import send_email_resend
from app.notify.ticket_created import notify_ticket_created


class TestNotifyEmailBcc(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_created_passes_cc_and_bcc_to_send_email(self) -> None:
        settings = NotifySettings(
            soc_notify_enabled=True,
            line_notify_enabled=False,
            soc_notify_from="xsoc@example.com",
            resend_api_key="re_test",
            soc_notify_to="soc@example.com",
            soc_notify_cc="cc@example.com",
            soc_notify_bcc="bcc@example.com",
        )

        with patch("app.notify.ticket_created.send_email", new=AsyncMock(return_value="resend")) as email_send:
            result = await notify_ticket_created(
                jira_key="AIXSOC-1",
                case_id="XSOC-1",
                summary="test",
                customer_code="JJ",
                source_id="stellar",
                external_id="case-1",
                platform="stellar",
                settings=settings,
            )

        self.assertTrue(result.get("sent"))
        email_send.assert_awaited_once()
        kwargs = email_send.await_args.kwargs
        self.assertEqual(kwargs["to_addrs"], ["soc@example.com"])
        self.assertEqual(kwargs["cc_addrs"], ["cc@example.com"])
        self.assertEqual(kwargs["bcc_addrs"], ["bcc@example.com"])
        self.assertEqual(result["email"]["cc"], ["cc@example.com"])
        self.assertEqual(result["email"]["bcc"], ["bcc@example.com"])

    async def test_resend_api_includes_bcc_payload(self) -> None:
        settings = NotifySettings(
            soc_notify_from="xsoc@example.com",
            resend_api_key="re_test",
        )
        captured: dict = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"id": "email-1"}

            text = ""

            reason_phrase = "OK"

        class FakeClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *args) -> None:
                return None

            async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
                captured["url"] = url
                captured["json"] = json
                return FakeResponse()

        with patch("app.notify.resend_api.httpx.AsyncClient", FakeClient):
            await send_email_resend(
                settings,
                to_addrs=["soc@example.com"],
                subject="test",
                body_text="body",
                cc_addrs=["cc@example.com"],
                bcc_addrs=["bcc@example.com"],
            )

        self.assertEqual(captured["json"]["to"], ["soc@example.com"])
        self.assertEqual(captured["json"]["cc"], ["cc@example.com"])
        self.assertEqual(captured["json"]["bcc"], ["bcc@example.com"])


if __name__ == "__main__":
    unittest.main()
