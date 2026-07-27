"""Tests for CYCRAFT_C normalizer."""

from __future__ import annotations

import unittest

from app.integrations.cycraft.normalizer import event_for_stellar_ingest, normalize_csr_report


class CsrNormalizerTests(unittest.TestCase):
    def test_flattens_endpoints(self) -> None:
        report = {
            "ReportType": "CYCRAFT_C",
            "ReportID": "abc123",
            "ReportTime": "2026-02-02T01:31:12Z",
            "Summary": {"Severity": 9, "Customer": "JJNET", "LastEventTime": "2026-02-02T01:30:00Z"},
            "Endpoints": [
                {
                    "EntityId": "Agent001",
                    "Name": "HOST-1",
                    "Severity": 9,
                    "IPAddress": ["10.0.0.5"],
                    "Group": "Default",
                }
            ],
        }
        events = normalize_csr_report(report, vendor="CyCraft", source="Xensor_EDR")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["alert_type"], "CYCRAFT_C")
        self.assertEqual(events[0]["event_id"], "csr-abc123-Agent001")
        self.assertNotIn("raw", event_for_stellar_ingest(events[0]))


if __name__ == "__main__":
    unittest.main()
