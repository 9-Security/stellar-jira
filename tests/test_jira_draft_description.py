"""Tests for Jira description formatting (stellar_case_detail_lines)."""

from __future__ import annotations

import unittest

from app.dates import format_detection_time
from app.notify.stellar_sample_case import (
    SAMPLE_MIDDLEWARE_CASE_ID,
    sample_stellar_notify_bundle,
    sample_stellar_notify_case,
)
from app.stellar.jira_draft import stellar_case_detail_lines


class TestJiraDraftDescription(unittest.TestCase):
    def test_new_description_format(self) -> None:
        case = sample_stellar_notify_case()
        bundle = sample_stellar_notify_bundle()

        lines = stellar_case_detail_lines(
            case,
            bundle,
            middleware_case_id=SAMPLE_MIDDLEWARE_CASE_ID,
            customer_code="JJNET",
            timezone_name="Asia/Taipei",
        )
        text = "\n".join(lines)
        expected_detection = format_detection_time(case["created_at"], timezone_name="Asia/Taipei")

        self.assertNotIn("Detection Source", text)
        self.assertNotIn("Stellar Case ID", text)
        self.assertNotIn("客戶代號", text)
        self.assertNotIn("Assignee", text)
        self.assertNotIn("事件狀態", text)
        self.assertNotIn("Created:", text)
        self.assertNotIn("Modified:", text)
        self.assertNotIn("(Stellar status)", text)
        self.assertNotIn("(Stellar name)", text)
        self.assertNotIn("Observables (sample)", text)

        self.assertIn("AIxSOC Ticket ID: 1123", text)
        self.assertIn("案件編號: XSOC-JJNET-260707-001", text)
        self.assertIn("告警名稱: LOLBIN process executed with a high integrity level", text)
        self.assertIn(f"偵測時間: {expected_detection}", text)
        self.assertIn("自動回應結果: Prevented (Blocked)", text)
        self.assertIn("host: Gary-Kuei (192.168.0.98)", text)
        self.assertIn("host: Gary-Kuei (192.168.233.222)", text)
        self.assertIn("user: GARY-KUEI\\Gary Kuei", text)
        self.assertIn("user: NT AUTHORITY\\SYSTEM", text)
        self.assertIn("process: YuantaCAPIServiSignAdapterSetup (2).exe", text)
        self.assertIn("Detail:", text)
        self.assertIn("MITRE Tactics: Privilege Escalation", text)
        self.assertEqual(text.count("user: GARY-KUEI\\Gary Kuei"), 1)


if __name__ == "__main__":
    unittest.main()
