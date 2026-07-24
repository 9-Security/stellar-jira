from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import NotifySettings
from app.notify.maiagent_personal import (
    _format_personal_body,
    notify_maiagent_personal,
)
from app.stellar_sync.runner import (
    _case_created_at_ms,
    _inject_maiagent_retry_cases,
    _schedule_maiagent_all_case,
)
from app.sync.state import SyncState


class TestMaiAgentAllCases(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = SyncState(Path(self.tmp.name) / "state.sqlite")
        self.state.init()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_baseline_is_never_claimed(self) -> None:
        self.state.mark_maiagent_case_baseline("stellar", "old-case")
        status = self.state.try_claim_maiagent_case(
            "stellar",
            "old-case",
            retry_after_seconds=600,
        )
        self.assertEqual(status, "done")
        self.assertEqual(self.state.maiagent_delivery_counts(), {"baseline": 1})

    def test_created_at_normalizes_seconds_and_iso(self) -> None:
        self.assertEqual(_case_created_at_ms({"created_at": 1_700_000_000}), 1_700_000_000_000)
        self.assertGreater(
            _case_created_at_ms({"created_at": "2026-07-16T09:00:00Z"}),
            0,
        )

    def test_all_cases_requires_explicit_line_target(self) -> None:
        # Empty ALL_CASES_LINE_TO must NOT borrow LINE_NOTIFY_TO (SOC channel).
        missing = NotifySettings(
            maiagent_all_cases_enabled=True,
            maiagent_api_key="key",
            maiagent_chatbot_id="bot",
            maiagent_all_cases_line_to=None,
            line_channel_access_token="token",
            line_notify_to="C" + "b" * 32,
        )
        self.assertFalse(missing.maiagent_all_cases_configured)

        explicit = NotifySettings(
            maiagent_all_cases_enabled=True,
            maiagent_api_key="key",
            maiagent_chatbot_id="bot",
            maiagent_all_cases_line_to="C" + "a" * 32,
            line_channel_access_token="token",
            line_notify_to="C" + "b" * 32,
        )
        self.assertTrue(explicit.maiagent_all_cases_configured)

    def test_post_create_shares_line_notify_to_when_override_empty(self) -> None:
        settings = NotifySettings(
            maiagent_notify_enabled=True,
            maiagent_api_key="key",
            maiagent_chatbot_id="bot",
            maiagent_notify_line_to=None,
            maiagent_notify_email_to=None,
            line_channel_access_token="token",
            line_notify_to="C" + "b" * 32,
        )
        self.assertTrue(settings.maiagent_notify_configured)

    def test_all_case_body_contains_analysis_without_email_wrapper(self) -> None:
        body = _format_personal_body(
            jira_key="AIXSOC-1",
            case_id="case-1",
            event_name="Suspicious alert",
            parsed={
                "executive_summary": "事件分析內容",
                "recommended_actions": ["隔離主機"],
            },
            raw_content="",
            display_label="MaiAgent 全案例因果分析",
            analysis_heading="MaiAgent AI 分析:",
            analysis_only=True,
        )

        self.assertTrue(body.startswith("MaiAgent AI 分析:\n"))
        self.assertIn("摘要：事件分析內容", body)
        self.assertNotIn("Jira:", body)
        self.assertNotIn("Case:", body)
        self.assertNotIn("事件:", body)
        self.assertNotIn("非正式 SOC 廣播", body)
        self.assertNotIn("MAIAGENT_NOTIFY_", body)

    async def test_root_cause_mode_sends_only_plain_analysis(self) -> None:
        settings = NotifySettings(
            maiagent_all_cases_enabled=True,
            maiagent_api_key="key",
            maiagent_chatbot_id="bot",
            line_channel_access_token="token",
            line_notify_to="C" + "b" * 32,
        )
        with patch(
            "app.notify.maiagent_personal.chatbot_completion",
            new=AsyncMock(
                return_value={
                    "content": "最可能的根因是遭竄改的排程工作觸發惡意程序。",
                    "conversation_id": "conversation-1",
                }
            ),
        ) as complete:
            with patch(
                "app.notify.maiagent_personal.send_line_notify",
                new=AsyncMock(
                    return_value={
                        "sent": True,
                        "recipients": ["C" + "b" * 32],
                    }
                ),
            ) as send_line:
                result = await notify_maiagent_personal(
                    jira_key="",
                    case_id="case-1",
                    stellar_case={"_id": "case-1"},
                    stellar_bundle={"alerts": [{"name": "Alert 1"}]},
                    settings=settings,
                    email_to_override="",
                    line_to_override=settings.line_notify_to,
                    body_heading="MaiAgent AI 分析:",
                    root_cause_only=True,
                    line_subject_override="",
                )

        self.assertTrue(result["sent"])
        self.assertIn(
            "只輸出一段連貫的繁體中文 Root Cause 分析正文",
            complete.await_args.kwargs["message"],
        )
        self.assertEqual(send_line.await_args.kwargs["subject"], "")
        self.assertEqual(
            send_line.await_args.kwargs["body_text"],
            "MaiAgent AI 分析:\n\n最可能的根因是遭竄改的排程工作觸發惡意程序。",
        )

    async def test_post_create_uses_shared_line_and_full_case(self) -> None:
        from app.notify.maiagent_personal import maybe_notify_maiagent_personal

        settings = NotifySettings(
            maiagent_notify_enabled=True,
            maiagent_notify_async=False,
            maiagent_api_key="key",
            maiagent_chatbot_id="bot",
            maiagent_notify_line_to=None,
            maiagent_notify_email_to=None,
            line_channel_access_token="token",
            line_notify_to="C" + "b" * 32,
        )
        with patch(
            "app.notify.maiagent_personal.chatbot_completion",
            new=AsyncMock(
                return_value={
                    "content": "全案根因分析內容。",
                    "conversation_id": "c1",
                }
            ),
        ) as complete:
            with patch(
                "app.notify.maiagent_personal.send_line_notify",
                new=AsyncMock(
                    return_value={"sent": True, "recipients": ["C" + "b" * 32]}
                ),
            ) as send_line:
                result = await maybe_notify_maiagent_personal(
                    jira_key="AIXSOC-99",
                    case_id="1220",
                    stellar_case={"_id": "abc", "severity": "Critical"},
                    stellar_bundle={"alerts": []},
                    settings=settings,
                )

        self.assertTrue(result["ok"])
        self.assertTrue(result["line"]["sent"])
        self.assertEqual(send_line.await_args.kwargs["to_ids"], ["C" + "b" * 32])
        self.assertIn("Root Cause", complete.await_args.kwargs["message"])
        self.assertTrue(
            send_line.await_args.kwargs["body_text"].startswith("MaiAgent AI 分析:")
        )

    async def test_failed_delivery_is_refetched_after_retry_delay(self) -> None:
        self.assertEqual(
            self.state.try_claim_maiagent_case(
                "stellar", "retry-case", retry_after_seconds=60
            ),
            "claimed",
        )
        self.state.finish_maiagent_case(
            "stellar",
            "retry-case",
            delivered=False,
            error="LINE failed",
        )
        with sqlite3.connect(self.state.path) as connection:
            connection.execute(
                "UPDATE maiagent_case_delivery SET claimed_at_ms=0 "
                "WHERE incident_id='retry-case'"
            )
            connection.commit()
        client = MagicMock()
        client.get_case = AsyncMock(
            return_value={"data": {"case": {"_id": "retry-case"}}}
        )
        settings = NotifySettings(
            maiagent_all_cases_enabled=True,
            maiagent_api_key="key",
            maiagent_chatbot_id="bot",
            maiagent_all_cases_line_to="C" + "a" * 32,
            line_channel_access_token="token",
            line_notify_enabled=False,
            soc_notify_enabled=False,
        )

        merged = await _inject_maiagent_retry_cases(
            [],
            source_id="stellar",
            state=self.state,
            client=client,
            settings=settings,
            dry_run=False,
        )

        self.assertEqual([case["_id"] for case in merged], ["retry-case"])

    async def test_new_case_schedules_dedicated_line_once(self) -> None:
        settings = NotifySettings(
            maiagent_all_cases_enabled=True,
            maiagent_api_key="key",
            maiagent_chatbot_id="bot",
            maiagent_all_cases_line_to="C" + "a" * 32,
            line_channel_access_token="token",
            line_notify_enabled=False,
            soc_notify_enabled=False,
        )
        client = MagicMock()
        client.fetch_case_bundle = AsyncMock(
            return_value={"case": {"_id": "new-case", "ticket_id": 99}}
        )
        result = {
            "ok": True,
            "line": {"sent": True, "recipients": ["C" + "a" * 32]},
        }

        with patch(
            "app.stellar_sync.runner.notify_maiagent_personal",
            new=AsyncMock(return_value=result),
        ) as notify:
            row, bundle = await _schedule_maiagent_all_case(
                state=self.state,
                source_id="stellar",
                case={"_id": "new-case", "ticket_id": 99},
                customer_code="JJEDR",
                client=client,
                settings=settings,
                jira_key="",
            )
            await asyncio.sleep(0.01)

        self.assertEqual(row["status"], "scheduled")
        self.assertIsInstance(bundle, dict)
        self.assertEqual(self.state.maiagent_delivery_counts(), {"delivered": 1})
        self.assertEqual(notify.await_args.kwargs["email_to_override"], "")
        self.assertEqual(
            notify.await_args.kwargs["line_to_override"],
            "C" + "a" * 32,
        )
        self.assertEqual(
            notify.await_args.kwargs["body_heading"],
            "MaiAgent AI 分析:",
        )
        self.assertTrue(notify.await_args.kwargs["analysis_only"])
        self.assertTrue(notify.await_args.kwargs["root_cause_only"])
        self.assertEqual(notify.await_args.kwargs["line_subject_override"], "")
        second, _ = await _schedule_maiagent_all_case(
            state=self.state,
            source_id="stellar",
            case={"_id": "new-case", "ticket_id": 99},
            customer_code="JJEDR",
            client=client,
            settings=settings,
            jira_key="",
        )
        self.assertEqual(second["status"], "done")
        client.fetch_case_bundle.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
