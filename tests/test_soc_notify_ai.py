"""Tests for SOC notify AI helpers."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.ai.groq_client import parse_json_object
from app.ai.soc_notify import generate_stellar_soc_ai_sections
from app.ai.stellar_context import build_stellar_soc_ai_context
from app.config import NotifySettings
from app.notify.ticket_created import _build_stellar_body


class TestSocNotifyAI(unittest.TestCase):
    def test_parse_json_object_from_fence(self) -> None:
        raw = 'Here is JSON:\n```json\n{"executive_summary":"a","event_description":"b","recommended_actions":["c"]}\n```'
        data = parse_json_object(raw)
        self.assertEqual(data["executive_summary"], "a")

    def test_build_context_includes_alerts(self) -> None:
        case = {"_id": "c1", "name": "Palo Alto Networks Cortex XDR (XDR Agent): WildFire Malware and 1 other", "severity": "High"}
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Malware",
                                    "description": "Suspicious executable detected",
                                    "action_pretty": "Detected",
                                }
                            }
                        }
                    ]
                }
            },
            "summary": {"data": {"tactics": ["Malware"], "techniques": ["T1204"]}},
        }
        ctx = build_stellar_soc_ai_context(case=case, bundle=bundle, middleware_case_id="XSOC-JJ-260701-001", customer_code="JJ")
        self.assertEqual(ctx["display_name"], "WildFire Malware")
        self.assertEqual(len(ctx["alerts"]), 1)

    def test_context_includes_decision_brief(self) -> None:
        case = {"_id": "c1", "name": "WildFire Malware", "severity": "Critical"}
        decision = {
            "action": "escalate",
            "escalation": "IR",
            "playbook_id": "PB-IR-MALWARE-BLOCKED",
            "isolate_host_advisory": False,
            "rule_hits": ["malware_blocked_ir_review"],
        }
        ctx = build_stellar_soc_ai_context(case=case, bundle={}, decision=decision)
        self.assertEqual(ctx["decision"]["playbook_id"], "PB-IR-MALWARE-BLOCKED")
        self.assertFalse(ctx["decision"]["isolate_host_advisory"])

    def test_alerts_sorted_blocked_malware_cortex_first(self) -> None:
        """Case 1220-style: Detected BIOC first in API → AI context still leads with Prevented Malware."""
        case = {"_id": "c1220", "size": 11, "severity": "Critical", "name": "WildFire Malware and 10 others"}
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Persistence",
                                    "action_pretty": "Detected",
                                    "case_id": None,
                                    "description": "protect.exe early boot",
                                }
                            }
                        },
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Execution",
                                    "action_pretty": "Detected",
                                    "description": "Elevation to SYSTEM",
                                }
                            }
                        },
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Malware",
                                    "name": "WildFire Malware",
                                    "action_pretty": "Prevented (Blocked)",
                                    "case_id": 3363,
                                    "description": "Suspicious executable detected",
                                }
                            }
                        },
                    ]
                }
            }
        }
        ctx = build_stellar_soc_ai_context(case=case, bundle=bundle)
        self.assertEqual(ctx["disposition"], "已阻擋")
        self.assertEqual(ctx["response_action"], "Prevented (Blocked)")
        self.assertIn("blocked", ctx["alerts_sort"].lower())
        top = ctx["alerts"][0]
        self.assertEqual(top["category"], "Malware")
        self.assertEqual(top["action"], "Prevented (Blocked)")
        self.assertEqual(top["cortex_case_id"], "3363")
        self.assertEqual(ctx["alerts"][1]["category"], "Persistence")

    def test_body_uses_jira_description_format_with_ai_sections(self) -> None:
        case = {"severity": "Critical", "name": "Test", "created_at": 1780000000000}
        body = _build_stellar_body(
            case=case,
            bundle={},
            case_id="XSOC-JJ-001",
            ai_sections={
                "executive_summary": "偵測到惡意程式活動。",
                "event_description": "攻擊者透過 mailx.exe 執行惡意行為。",
                "recommended_actions": ["隔離主機", "保全日誌"],
            },
        )
        self.assertIn("AI SOC 分析師摘要:", body)
        self.assertIn("偵測到惡意程式活動。", body)
        self.assertIn("案件編號: XSOC-JJ-001", body)
        self.assertIn("告警名稱: Test", body)
        self.assertIn("嚴重程度: Critical", body)
        self.assertIn("自動回應結果:", body)
        self.assertIn("偵測時間:", body)
        self.assertIn("事件描述:", body)
        self.assertIn("攻擊者透過 mailx.exe", body)
        self.assertIn("1. 隔離主機", body)
        self.assertIn("請 SOC 人員覆核", body)
        self.assertNotIn("主機資訊", body)
        self.assertNotIn("檔案路徑:", body)


class TestGenerateStellarSocAI(unittest.IsolatedAsyncioTestCase):
    async def test_generate_sections_ok(self) -> None:
        settings = NotifySettings(
            soc_notify_ai_enabled=True,
            soc_notify_ai_api_key="test-key",
            soc_notify_ai_model="llama-3.3-70b-versatile",
        )
        mock_payload = {
            "executive_summary": "摘要",
            "event_description": "描述",
            "recommended_actions": ["步驟一"],
        }
        with patch(
            "app.ai.soc_notify.chat_completion_json",
            new=AsyncMock(return_value=mock_payload),
        ):
            result = await generate_stellar_soc_ai_sections(
                case={"_id": "x", "severity": "High", "name": "Alert"},
                bundle={},
                middleware_case_id="XSOC-1",
                customer_code="JJ",
                settings=settings,
            )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("executive_summary"), "摘要")

    async def test_generate_passes_decision_into_context(self) -> None:
        settings = NotifySettings(
            soc_notify_ai_enabled=True,
            soc_notify_ai_api_key="test-key",
        )
        mock_payload = {
            "executive_summary": "摘要",
            "event_description": "描述",
            "recommended_actions": ["步驟一"],
        }
        with patch(
            "app.ai.soc_notify.chat_completion_json",
            new=AsyncMock(return_value=mock_payload),
        ) as mock_chat:
            await generate_stellar_soc_ai_sections(
                case={"_id": "x", "severity": "High", "name": "Alert"},
                bundle={},
                middleware_case_id="XSOC-1",
                customer_code="JJ",
                settings=settings,
                decision={
                    "escalation": "IR",
                    "playbook_id": "PB-IR-MALWARE-BLOCKED",
                    "isolate_host_advisory": False,
                },
            )
        user_prompt = mock_chat.await_args.kwargs["user_prompt"]
        self.assertIn("PB-IR-MALWARE-BLOCKED", user_prompt)
        self.assertIn('"isolate_host_advisory": false', user_prompt)

    async def test_generate_skipped_when_disabled(self) -> None:
        settings = NotifySettings(soc_notify_ai_enabled=False)
        result = await generate_stellar_soc_ai_sections(
            case={"_id": "x"},
            bundle={},
            settings=settings,
        )
        self.assertTrue(result.get("skipped"))


if __name__ == "__main__":
    unittest.main()
