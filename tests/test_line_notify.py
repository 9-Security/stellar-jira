"""Tests for LINE Messaging API notifications."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.config import NotifySettings
from app.notify.line_bot import (
    LINE_TEXT_MAX_LEN,
    list_line_follower_ids,
    line_recipient_id_hint,
    parse_line_recipient_list,
    push_line_text,
    send_line_notify,
    _truncate_line_text,
)

_VALID_USER = "U" + "a" * 32
_VALID_GROUP = "C" + "b" * 32
_VALID_ROOM = "R" + "c" * 32


class TestLineNotify(unittest.TestCase):
    def test_line_recipient_id_hint_short_id(self) -> None:
        hint = line_recipient_id_hint("U601913152")
        self.assertIsNotNone(hint)
        self.assertIn("need 33", hint or "")

    def test_parse_line_recipient_list(self) -> None:
        raw = f"{_VALID_USER}, {_VALID_GROUP}; {_VALID_ROOM}"
        self.assertEqual(parse_line_recipient_list(raw), [_VALID_USER, _VALID_GROUP, _VALID_ROOM])
        self.assertEqual(parse_line_recipient_list(f"bad id, {_VALID_USER}"), [_VALID_USER])
        self.assertEqual(parse_line_recipient_list("U601913152"), [])

    def test_truncate_line_text(self) -> None:
        long_text = "x" * (LINE_TEXT_MAX_LEN + 100)
        truncated = _truncate_line_text(long_text)
        self.assertLessEqual(len(truncated), LINE_TEXT_MAX_LEN)
        self.assertTrue(truncated.endswith("...(訊息已截斷)"))

    def test_send_line_notify_skips_when_not_configured(self) -> None:
        async def _run() -> None:
            settings = NotifySettings(line_channel_access_token=None)
            result = await send_line_notify(
                to_ids=[_VALID_USER],
                subject="test",
                body_text="body",
                settings=settings,
            )
            self.assertEqual(result, {"skipped": True, "reason": "not_configured"})

        import asyncio

        asyncio.run(_run())

    def test_list_line_follower_ids(self) -> None:
        async def _run() -> None:
            from unittest.mock import MagicMock

            settings = NotifySettings(line_channel_access_token="line-token")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"userIds": [_VALID_USER], "next": None}
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("app.notify.line_bot.httpx.AsyncClient", return_value=mock_client):
                ids = await list_line_follower_ids(settings)

            self.assertEqual(ids, [_VALID_USER])

        import asyncio

        asyncio.run(_run())

    def test_send_line_notify_partial_failure(self) -> None:
        async def _run() -> None:
            settings = NotifySettings(
                line_channel_access_token="line-token",
                line_notify_to="Uone1234567890,Utwo1234567890",
            )

            valid_b = "U" + "b" * 32

            async def _push(settings_obj, *, to_id: str, text: str):
                if to_id == _VALID_USER:
                    return {"ok": True}
                raise ValueError("LINE API 400: invalid recipient")

            with patch("app.notify.line_bot.push_line_text", side_effect=_push):
                result = await send_line_notify(
                    to_ids=[_VALID_USER, valid_b],
                    subject="subject",
                    body_text="body",
                    settings=settings,
                )

            self.assertTrue(result.get("sent"))
            self.assertTrue(result.get("partial"))
            self.assertEqual(result.get("recipients"), [_VALID_USER])

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
