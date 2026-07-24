"""Tests for Cortex XDR report helpers."""

from __future__ import annotations

import unittest
from datetime import date

from app.report.report_branding import REPORT_COVER_TITLE, report_platform
from app.report.stellar_cortex_summary import build_mitre_summary_from_cortex_rows, build_top_cortex_cases, process_cortex_report_data
from app.stellar.cortex_report import is_cortex_source, normalize_cortex_row
from app.stellar.report_runner import monthly_run_dir_name
from app.stellar.tenant_model import StellarTenant


class TestCortexReport(unittest.TestCase):
    def test_is_cortex_source_palo_alto(self) -> None:
        src = {"palo_alto_networks": {"name": "WildFire Malware", "category": "Malware"}}
        self.assertTrue(is_cortex_source(src))

    def test_is_cortex_source_xdr_event(self) -> None:
        src = {"xdr_event": {"description": "Cortex XDR Agent identified malware"}}
        self.assertTrue(is_cortex_source(src))

    def test_is_cortex_source_negative(self) -> None:
        self.assertFalse(is_cortex_source({"darktrace": {"mitreid": "T1001"}}))

    def test_report_branding(self) -> None:
        self.assertEqual(REPORT_COVER_TITLE, "XMDR 託管式偵測與回應服務")
        self.assertEqual(report_platform("Cortex XDR"), "Cortex XDR via AI SOC")
        self.assertEqual(report_platform("Darktrace"), "Darktrace via AI SOC")

    def test_monthly_run_dir_name(self) -> None:
        tenant = StellarTenant(source_id="jjnet", customer_code="JJ", products=["cortex"])
        name = monthly_run_dir_name(tenant, "cortex", timezone_name="UTC")
        self.assertRegex(name, r"^jjnet_cortex_\d{14}$")

    def test_process_cortex_report_data_cover(self) -> None:
        rows = [
            normalize_cortex_row(
                case={
                    "_id": "c1",
                    "name": "Palo Alto Networks Cortex XDR: Malware",
                    "severity": "High",
                    "status": "New",
                    "created_at": 1_700_000_000_000,
                },
                alert_doc={
                    "_source": {
                        "palo_alto_networks": {
                            "name": "WildFire Malware",
                            "category": "Malware",
                            "action_pretty": "Prevented (Blocked)",
                        }
                    },
                    "write_time": 1_700_000_000_000,
                },
                mitre_tactics=["TA0002 Execution"],
            )
        ]
        data = process_cortex_report_data(
            rows,
            date(2026, 5, 1),
            date(2026, 5, 31),
            tenant_label="客戶: JJNET",
        )
        self.assertEqual(data["cover"]["title"], REPORT_COVER_TITLE)
        self.assertEqual(data["platform"], "Cortex XDR via AI SOC")
        self.assertEqual(data["issues_count"], 1)
        self.assertIn("Malware", data["incidents"][0][3])

    def test_top_cortex_cases_one_row_per_case(self) -> None:
        rows = [
            {
                "case_id": "c1",
                "case_name": "Palo Alto Networks Cortex XDR (XDR Agent): WildFire Malware and 3 others",
                "case_severity": "High",
                "case_status": "New",
                "case_created_ms": 2,
                "alert_name": "alert-a",
                "alert_category": "Malware",
            },
            {
                "case_id": "c1",
                "case_name": "Palo Alto Networks Cortex XDR (XDR Agent): WildFire Malware and 3 others",
                "case_severity": "High",
                "case_status": "New",
                "case_created_ms": 2,
                "alert_name": "alert-b",
                "alert_category": "Malware",
            },
            {
                "case_id": "c2",
                "case_name": "Palo Alto Networks Cortex XDR (XDR Agent): Kernel Privilege Escalation",
                "case_severity": "Medium",
                "case_status": "New",
                "case_created_ms": 1,
                "alert_category": "Exploit",
            },
        ]
        top = build_top_cortex_cases(rows)
        filled = [row for row in top if row[3] != "無資料"]
        self.assertEqual(len(filled), 2)
        self.assertIn("WildFire Malware", filled[0][3])
        self.assertNotIn("and 3 others", filled[0][3])

    def test_mitre_summary_from_cortex_rows(self) -> None:
        rows = [
            {
                "case_id": "c1",
                "case_severity": "High",
                "mitre_tactics": ["TA0002 Execution"],
            },
            {
                "case_id": "c1",
                "case_severity": "High",
                "mitre_tactics": ["TA0002 Execution"],
            },
        ]
        summary = build_mitre_summary_from_cortex_rows(rows)
        self.assertEqual(summary["alerts_with_mitre"], 2)
        self.assertEqual(summary["cases_with_mitre"], 1)
        self.assertEqual(len(summary["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
