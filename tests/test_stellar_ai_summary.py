"""Tests for native Stellar AI Summary extraction and Jira formatting."""

from __future__ import annotations

import unittest

from app.stellar.ai_summary import (
    ai_summary_triage_state,
    extract_ai_case_triage,
    format_ai_summary_comment,
)


class TestStellarAISummary(unittest.TestCase):
    def test_partial_summary_is_not_ready(self) -> None:
        payload = {"data": {"aiSummary": {"triage_state": "ELIGIBLE"}}}
        self.assertIsNone(extract_ai_case_triage(payload))
        self.assertEqual(ai_summary_triage_state(payload), "ELIGIBLE")

    def test_extract_and_format_populated_summary(self) -> None:
        payload = {
            "data": {
                "aiSummary": {
                    "triage_state": "COMPLETED",
                    "ai_case_triage": {
                        "summary": {
                            "concise_summary": "偵測到可疑 PowerShell。",
                            "timeline": "10:00 執行 PowerShell",
                            "hypothesis": "可能為未授權腳本",
                            "key_entities_and_relations": "host-a → user-a",
                            "recommendations": "確認操作人員並檢查腳本",
                        },
                        "verdict": "True Positive",
                        "verdict_reasoning": "行為與已知攻擊鏈一致",
                    },
                }
            }
        }
        triage = extract_ai_case_triage(payload)
        assert triage is not None
        self.assertEqual(triage["verdict"], "True Positive")
        comment = format_ai_summary_comment(payload)
        self.assertIn("Stellar Cyber AI Summary", comment)
        self.assertIn("偵測到可疑 PowerShell", comment)
        self.assertIn("True Positive", comment)
        self.assertIn("請由 SOC 人員覆核", comment)


if __name__ == "__main__":
    unittest.main()
