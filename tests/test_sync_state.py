"""Tests for SQLite sync state (claims, pending, case sequences)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.sync.state import PENDING_JIRA_KEY, SyncState


class TestSyncState(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.state = SyncState(Path(self._tmpdir.name) / "test.sqlite")
        self.state.init(legacy_source_id="default")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_try_claim_and_record(self) -> None:
        self.assertEqual(self.state.try_claim("src1", "inc-1"), "claimed")
        self.assertEqual(self.state.try_claim("src1", "inc-1"), "pending")
        self.state.record("src1", "inc-1", "XSOC-1")
        self.assertEqual(self.state.try_claim("src1", "inc-1"), "synced")
        self.assertTrue(self.state.has_incident("src1", "inc-1"))

    def test_release_claim_clears_pending(self) -> None:
        self.assertEqual(self.state.try_claim("src1", "inc-2"), "claimed")
        self.state.release_claim("src1", "inc-2")
        self.assertEqual(self.state.try_claim("src1", "inc-2"), "claimed")

    def test_pending_not_counted_as_synced(self) -> None:
        self.state.try_claim("src1", "inc-3")
        self.assertFalse(self.state.has_incident("src1", "inc-3"))
        self.assertEqual(self.state.get_jira_key("src1", "inc-3"), PENDING_JIRA_KEY)

    def test_case_sequence_increments(self) -> None:
        self.assertEqual(self.state.increment_case_sequence("JJ", "260624"), 1)
        self.assertEqual(self.state.increment_case_sequence("JJ", "260624"), 2)
        self.assertEqual(self.state.increment_case_sequence("AB", "260624"), 1)

    def test_lookup_incident_by_jira_key(self) -> None:
        self.state.record("stellar", "abc123", "AIXSOC-42")
        self.assertEqual(
            self.state.lookup_incident_by_jira_key("AIXSOC-42", source_id="stellar"),
            "abc123",
        )
        self.assertIsNone(
            self.state.lookup_incident_by_jira_key(PENDING_JIRA_KEY, source_id="stellar"),
        )

    def test_record_tenant_metadata_and_counts(self) -> None:
        self.state.record(
            "stellar",
            "case-tenant",
            "AIXSOC-43",
            tenant_source_id="jjnet",
            tenant_id="tenant-1",
            tenant_name="JJNET",
            customer_code="jj",
        )
        self.assertEqual(self.state.tenant_link_counts(), {"jjnet": 1})

    def test_quarantine_round_trip(self) -> None:
        case = {
            "_id": "case-unknown",
            "cust_id": "unknown-id",
            "tenant_name": "Unknown",
            "modified_at": 123,
        }
        self.state.quarantine_case("stellar", case, reason="unknown_tenant_id")
        rows = self.state.list_quarantined_cases("stellar")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["case"]["_id"], "case-unknown")
        self.assertEqual(rows[0]["reason"], "unknown_tenant_id")
        self.state.remove_quarantined_case("stellar", "case-unknown")
        self.assertEqual(self.state.list_quarantined_cases("stellar"), [])

    def test_stellar_ai_summary_delivery_retry_and_finish(self) -> None:
        self.assertEqual(
            self.state.try_claim_stellar_ai_summary(
                "stellar",
                "case-ai",
                jira_key="AIXSOC-9",
                retry_after_seconds=300,
                max_attempts=3,
            ),
            "claimed",
        )
        self.state.finish_stellar_ai_summary(
            "stellar",
            "case-ai",
            status="waiting",
            payload={"data": {"aiSummary": {"triage_state": "ELIGIBLE"}}},
        )
        self.assertEqual(
            self.state.try_claim_stellar_ai_summary(
                "stellar",
                "case-ai",
                jira_key="AIXSOC-9",
                retry_after_seconds=300,
                max_attempts=3,
            ),
            "retry_wait",
        )
        self.state.finish_stellar_ai_summary(
            "stellar",
            "case-ai",
            status="delivered",
            payload={"data": {"aiSummary": {"ai_case_triage": {"verdict": "TP"}}}},
        )
        self.assertEqual(
            self.state.try_claim_stellar_ai_summary(
                "stellar",
                "case-ai",
                jira_key="AIXSOC-9",
                retry_after_seconds=300,
                max_attempts=3,
            ),
            "delivered",
        )
        row = self.state.get_stellar_ai_summary_delivery("stellar", "case-ai")
        assert row is not None
        self.assertEqual(row["status"], "delivered")
        self.assertIn("ai_case_triage", row["payload_json"])


if __name__ == "__main__":
    unittest.main()
