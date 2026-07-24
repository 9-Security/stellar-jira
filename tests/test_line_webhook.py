"""Tests for LINE webhook verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.config import NotifySettings
from app.main import app
from app.notify.line_webhook import (
    extract_line_reply_actions,
    extract_line_source_ids,
    format_line_id_reply_text,
    parse_line_webhook_events,
    record_line_source_ids,
    verify_line_signature,
)


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class TestLineWebhookHelpers(unittest.TestCase):
    def test_verify_line_signature(self) -> None:
        body = b'{"events":[]}'
        secret = "test-secret"
        self.assertTrue(verify_line_signature(body=body, signature=_sign(body, secret), channel_secret=secret))
        self.assertFalse(verify_line_signature(body=body, signature="bad", channel_secret=secret))

    def test_extract_line_source_ids(self) -> None:
        events = [
            {"type": "message", "source": {"type": "user", "userId": "Uabc1234567890"}},
            {"type": "join", "source": {"type": "group", "groupId": "Cgroup123456789"}},
        ]
        self.assertEqual(
            extract_line_source_ids(events),
            [
                {"id": "Uabc1234567890", "type": "user"},
                {"id": "Cgroup123456789", "type": "group"},
            ],
        )

    def test_parse_line_webhook_events(self) -> None:
        body = json.dumps({"events": [{"type": "follow"}]}).encode("utf-8")
        self.assertEqual(parse_line_webhook_events(body), [{"type": "follow"}])

    def test_extract_line_reply_actions(self) -> None:
        events = [
            {
                "type": "message",
                "replyToken": "token-1",
                "source": {"type": "user", "userId": "Uabc1234567890"},
            }
        ]
        self.assertEqual(
            extract_line_reply_actions(events),
            [{"reply_token": "token-1", "id": "Uabc1234567890", "type": "user"}],
        )

    def test_extract_line_reply_actions_group_prefers_group_id(self) -> None:
        group_id = "C" + "b" * 32
        user_id = "U" + "a" * 32
        events = [
            {
                "type": "message",
                "replyToken": "token-2",
                "source": {
                    "type": "group",
                    "groupId": group_id,
                    "userId": user_id,
                },
            }
        ]
        self.assertEqual(
            extract_line_reply_actions(events),
            [{"reply_token": "token-2", "id": group_id, "type": "group"}],
        )

    def test_format_line_id_reply_text(self) -> None:
        text = format_line_id_reply_text(line_id="Uabc1234567890", source_type="user")
        self.assertIn("Uabc1234567890", text)
        self.assertIn("LINE_NOTIFY_TO", text)

    def test_record_line_source_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "line_recipients.json"
            record_line_source_ids([{"id": "Uabc1234567890", "type": "user"}], store_path=path)
            record_line_source_ids([{"id": "Uabc1234567890", "type": "user"}], store_path=path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["recipients"]), 1)
            self.assertEqual(data["recipients"][0]["id"], "Uabc1234567890")


class TestLineWebhookRoute(unittest.TestCase):
    def test_line_webhook_rejects_when_secret_not_configured(self) -> None:
        settings = NotifySettings(line_channel_secret=None)
        with patch("app.routers.line_webhook.get_notify_settings", return_value=settings):
            client = TestClient(app)
            body = {"destination": "123", "events": []}
            resp = client.post("/v1/webhooks/line", json=body)
        self.assertEqual(resp.status_code, 503)

    def test_line_webhook_rejects_bad_signature_when_secret_set(self) -> None:
        settings = NotifySettings(line_channel_secret="test-secret")
        with patch("app.routers.line_webhook.get_notify_settings", return_value=settings):
            client = TestClient(app)
            resp = client.post(
                "/v1/webhooks/line",
                content=b'{"events":[]}',
                headers={"Content-Type": "application/json", "X-Line-Signature": "invalid"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_line_webhook_accepts_valid_signature(self) -> None:
        settings = NotifySettings(
            line_channel_secret="test-secret",
            line_channel_access_token="line-token",
        )
        body = b'{"events":[{"type":"follow","replyToken":"rt-1","source":{"type":"user","userId":"Uabc1234567890"}}]}'
        with patch("app.routers.line_webhook.get_notify_settings", return_value=settings):
            with patch("app.routers.line_webhook.record_line_source_ids") as record:
                with patch("app.routers.line_webhook.reply_line_text", new_callable=AsyncMock) as reply:
                    client = TestClient(app)
                    resp = client.post(
                        "/v1/webhooks/line",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Line-Signature": _sign(body, "test-secret"),
                        },
                    )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True, "events": 1, "replied": 1})
        record.assert_called_once()
        reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
