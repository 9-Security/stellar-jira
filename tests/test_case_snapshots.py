"""Tests for Stellar case snapshot archive (Decision Dataset raw layer)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.decision.store import DecisionStore
from app.sync.case_snapshots import (
    CaseSnapshotStore,
    get_case_snapshot_store,
    select_milestone_keep_ids,
)


class TestCaseSnapshots(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.sqlite"
        self.store = CaseSnapshotStore(self.db)
        self.store.init()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_idempotent_same_modified_at(self) -> None:
        bundle = {
            "case": {"_id": "abc", "modified_at": 1000, "severity": "High", "name": "Test"},
            "alerts": {"data": {"docs": [{"_source": {"name": "alert1"}}]}},
            "observables": {"observables": {"host": [{"hostname": "h1"}]}},
            "summary": {"data": {"tactics": ["Malware"]}},
        }
        s1 = self.store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="abc",
            bundle=bundle,
            customer_code="JJ",
            modified_at_ms=1000,
        )
        s2 = self.store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="abc",
            bundle=bundle,
            customer_code="JJ",
            modified_at_ms=1000,
        )
        self.assertEqual(s1, s2)
        latest = self.store.get_latest("stellar", "abc")
        assert latest is not None
        loaded = self.store.load_bundle_payload(latest)
        self.assertEqual(loaded["case"]["severity"], "High")
        self.assertIn("alerts", loaded)

    def test_new_snapshot_when_modified_at_changes(self) -> None:
        bundle1 = {"case": {"_id": "x", "modified_at": 1}, "alerts": {"n": 1}}
        bundle2 = {"case": {"_id": "x", "modified_at": 2}, "alerts": {"n": 2}}
        s1 = self.store.upsert_bundle(source_id="stellar", stellar_case_id="x", bundle=bundle1)
        s2 = self.store.upsert_bundle(source_id="stellar", stellar_case_id="x", bundle=bundle2)
        self.assertNotEqual(s1, s2)

    def test_file_offload_when_too_large(self) -> None:
        archive_dir = Path(self.tmp.name) / "archive"
        huge_alerts = {"data": {"docs": [{"_source": {"blob": "x" * 3_000_000}}]}}
        bundle = {"case": {"_id": "big", "modified_at": 9}, "alerts": huge_alerts}
        sid = self.store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="big",
            bundle=bundle,
            archive_dir=archive_dir,
            max_inline_bytes=1000,
        )
        row = self.store.get_by_id(sid or "")
        assert row is not None
        self.assertEqual(row["storage_mode"], "file")
        payload = self.store.load_bundle_payload(row)
        self.assertIn("alerts", payload)

    def test_attach_ai_summary_to_inline_snapshot(self) -> None:
        self.store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="ai-inline",
            bundle={"case": {"_id": "ai-inline", "modified_at": 1}, "alerts": {}},
        )
        ai_summary = {
            "data": {
                "aiSummary": {
                    "ai_case_triage": {
                        "summary": {"concise_summary": "Native AI summary"},
                        "verdict": "True Positive",
                    }
                }
            }
        }
        self.assertTrue(
            self.store.attach_ai_summary("stellar", "ai-inline", ai_summary)
        )
        row = self.store.get_latest("stellar", "ai-inline")
        assert row is not None
        loaded = self.store.load_bundle_payload(row)
        self.assertEqual(
            loaded["ai_summary"]["data"]["aiSummary"]["ai_case_triage"]["verdict"],
            "True Positive",
        )

    def test_attach_ai_summary_to_file_snapshot(self) -> None:
        archive_dir = Path(self.tmp.name) / "archive-ai"
        self.store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="ai-file",
            bundle={
                "case": {"_id": "ai-file", "modified_at": 2},
                "alerts": {"blob": "x" * 2000},
            },
            archive_dir=archive_dir,
            max_inline_bytes=1000,
        )
        ai_summary = {"data": {"aiSummary": {"triage_state": "ELIGIBLE"}}}
        self.assertTrue(self.store.attach_ai_summary("stellar", "ai-file", ai_summary))
        row = self.store.get_latest("stellar", "ai-file")
        assert row is not None
        loaded = self.store.load_bundle_payload(row)
        self.assertEqual(
            loaded["ai_summary"]["data"]["aiSummary"]["triage_state"],
            "ELIGIBLE",
        )

    def test_replace_snapshot_on_severity_escalation_same_modified_at(self) -> None:
        bundle_low = {
            "case": {"_id": "esc", "modified_at": 500, "severity": "Medium"},
            "alerts": {"data": {"docs": []}},
        }
        bundle_high = {
            "case": {"_id": "esc", "modified_at": 500, "severity": "High"},
            "alerts": {"data": {"docs": [{"_source": {"name": "new"}}]}},
        }
        s1 = self.store.upsert_bundle(source_id="stellar", stellar_case_id="esc", bundle=bundle_low)
        s2 = self.store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="esc",
            bundle=bundle_high,
            allow_replace_on_escalation=True,
        )
        self.assertNotEqual(s1, s2)
        latest = self.store.get_latest("stellar", "esc")
        assert latest is not None
        loaded = self.store.load_bundle_payload(latest)
        self.assertEqual(loaded["case"]["severity"], "High")

    def test_no_replace_without_escalation_flag(self) -> None:
        bundle_low = {"case": {"_id": "nesc", "modified_at": 1, "severity": "Low"}, "alerts": {}}
        bundle_high = {"case": {"_id": "nesc", "modified_at": 1, "severity": "High"}, "alerts": {"x": 1}}
        s1 = self.store.upsert_bundle(source_id="stellar", stellar_case_id="nesc", bundle=bundle_low)
        s2 = self.store.upsert_bundle(source_id="stellar", stellar_case_id="nesc", bundle=bundle_high)
        self.assertEqual(s1, s2)
        latest = self.store.get_latest("stellar", "nesc")
        assert latest is not None
        loaded = self.store.load_bundle_payload(latest)
        self.assertEqual(loaded["case"]["severity"], "Low")

    def test_decision_links_snapshot_id(self) -> None:
        dstore = DecisionStore(self.db)
        dstore.init()
        sid = self.store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="link1",
            bundle={"case": {"_id": "link1", "modified_at": 5}, "alerts": {}},
        )
        eid = dstore.record_decision(
            source_id="stellar",
            stellar_case_id="link1",
            decision={"action": "create_ticket", "escalation": "L1", "rule_hits": []},
            snapshot_id=sid,
        )
        row = dstore.get_by_event_id(eid)
        assert row is not None
        self.assertEqual(row.get("snapshot_id"), sid)

    def test_milestone_keep_collapses_same_severity_spam(self) -> None:
        rows = [
            {"snapshot_id": "a", "modified_at_ms": 1, "captured_at": "t1", "severity": "Medium"},
            {"snapshot_id": "b", "modified_at_ms": 2, "captured_at": "t2", "severity": "Medium"},
            {"snapshot_id": "c", "modified_at_ms": 3, "captured_at": "t3", "severity": "Medium"},
            {"snapshot_id": "d", "modified_at_ms": 4, "captured_at": "t4", "severity": "Medium"},
        ]
        keep = select_milestone_keep_ids(rows)
        # earliest + latest (+ first Medium == earliest) → 2
        self.assertEqual(keep, {"a", "d"})

    def test_milestone_keep_severity_ladder_and_protected(self) -> None:
        rows = [
            {"snapshot_id": "l", "modified_at_ms": 1, "severity": "Low"},
            {"snapshot_id": "m", "modified_at_ms": 2, "severity": "Medium"},
            {"snapshot_id": "m2", "modified_at_ms": 3, "severity": "Medium"},
            {"snapshot_id": "h", "modified_at_ms": 4, "severity": "High"},
            {"snapshot_id": "h2", "modified_at_ms": 5, "severity": "High"},
        ]
        keep = select_milestone_keep_ids(rows, protected_ids={"m2"})
        self.assertIn("l", keep)
        self.assertIn("m", keep)
        self.assertIn("m2", keep)
        self.assertIn("h", keep)
        self.assertIn("h2", keep)  # latest
        self.assertNotIn("x", keep)

    def test_prune_case_deletes_intermediate(self) -> None:
        for i, sev in enumerate(["Medium", "Medium", "Medium", "Medium"], start=1):
            self.store.upsert_bundle(
                source_id="stellar",
                stellar_case_id="spam",
                bundle={"case": {"_id": "spam", "modified_at": i * 10, "severity": sev}, "alerts": {}},
            )
        plan = self.store.prune_case("stellar", "spam", dry_run=False)
        self.assertEqual(plan["total"], 4)
        self.assertEqual(plan["keep"], 2)
        self.assertEqual(plan["deleted"], 2)
        left = self.store.list_for_case("stellar", "spam", resolve_severity=False)
        self.assertEqual(len(left), 2)

    def test_autoprune_on_upsert(self) -> None:
        for i in range(1, 6):
            self.store.upsert_bundle(
                source_id="stellar",
                stellar_case_id="auto",
                bundle={
                    "case": {"_id": "auto", "modified_at": i, "severity": "High"},
                    "alerts": {"n": i},
                },
                autoprune=True,
            )
        left = self.store.list_for_case("stellar", "auto", resolve_severity=False)
        self.assertEqual(len(left), 2)


class TestGetCaseSnapshotStore(unittest.TestCase):
    def test_factory(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            from app.config import get_stellar_settings

            get_stellar_settings.cache_clear()
            # Uses default path from settings; just ensure init works on temp copy
            path = Path(tmp.name) / "s.sqlite"
            store = CaseSnapshotStore(path)
            store.init()
            self.assertTrue(path.is_file())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
