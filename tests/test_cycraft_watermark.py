"""Unit tests for poll watermark helpers."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.integrations.cycraft.normalizer import event_for_stellar_ingest
from app.integrations.cycraft.watermark import bump_alert_watermark, bump_incident_watermark


class WatermarkTests(unittest.TestCase):
    def test_bump_alert_uses_ref_created_only(self) -> None:
        current = datetime(2026, 7, 24, 7, 0, tzinfo=timezone.utc)
        item = {
            "payload": {
                "_xcockpit_alert_ref": {"created": "2026-07-24T07:57:02Z"},
                "ReportTime": "2026-07-24 15:56:55",
            }
        }
        bumped = bump_alert_watermark(current, item)
        self.assertEqual(bumped, datetime(2026, 7, 24, 7, 57, 2, tzinfo=timezone.utc))

    def test_bump_alert_ignores_report_time_without_ref(self) -> None:
        current = datetime(2026, 7, 24, 7, 0, tzinfo=timezone.utc)
        item = {"payload": {"ReportTime": "2026-07-24 15:56:55"}}
        self.assertEqual(bump_alert_watermark(current, item), current)

    def test_bump_incident_uses_created_only(self) -> None:
        current = datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc)
        item = {
            "payload": {
                "created": "2026-07-24T08:10:00+08:00",
                "last_event_time": "2026-07-24T09:00:00Z",
            }
        }
        bumped = bump_incident_watermark(current, item)
        self.assertEqual(bumped, datetime(2026, 7, 24, 0, 10, tzinfo=timezone.utc))

    def test_bump_incident_does_not_use_last_event_time(self) -> None:
        current = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
        item = {"payload": {"last_event_time": "2026-07-24T09:00:00Z"}}
        self.assertEqual(bump_incident_watermark(current, item), current)


class NormalizerIngestTests(unittest.TestCase):
    def test_event_for_stellar_ingest_strips_raw(self) -> None:
        event = {"event_id": "edr-1", "vendor": "CyCraft", "raw": {"huge": "payload"}}
        ingested = event_for_stellar_ingest(event)
        self.assertNotIn("raw", ingested)
        self.assertEqual(ingested["event_id"], "edr-1")


if __name__ == "__main__":
    unittest.main()
