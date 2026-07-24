"""Tests for XSOC case number resolution."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.demo.case_number import (
    display_case_number,
    enrich_case_row,
    load_case_number_index,
    resolve_case_lookup_key,
)
from app.decision.store import DecisionStore
from app.sync.state import SyncState


class TestCaseNumber(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.sqlite"
        state = SyncState(self.db)
        state.init(legacy_source_id="stellar")
        state.record("stellar", "case-abc", "AIXSOC-9", customer_code="JJNET")
        store = DecisionStore(self.db)
        store.init()
        store.record_decision(
            source_id="stellar",
            stellar_case_id="case-abc",
            middleware_case_id="XSOC-JJNET-260724-001",
            jira_key="AIXSOC-9",
            customer_code="JJNET",
            decision={"action": "create_ticket", "escalation": "L1"},
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_index(self) -> None:
        index = load_case_number_index(self.db, "stellar")
        self.assertEqual(index.by_stellar["case-abc"], "XSOC-JJNET-260724-001")
        self.assertEqual(index.by_jira["AIXSOC-9"], "XSOC-JJNET-260724-001")

    def test_display_prefers_xsoc(self) -> None:
        index = load_case_number_index(self.db, "stellar")
        label = display_case_number(
            stellar_case_id="case-abc",
            jira_key="AIXSOC-9",
            index=index,
        )
        self.assertEqual(label, "XSOC-JJNET-260724-001")

    def test_resolve_lookup_key(self) -> None:
        key = resolve_case_lookup_key(
            "XSOC-JJNET-260724-001",
            path=self.db,
            source_id="stellar",
        )
        self.assertEqual(key, "case-abc")

    def test_enrich_row(self) -> None:
        index = load_case_number_index(self.db, "stellar")
        row = enrich_case_row(
            {"stellar_case_id": "case-abc", "jira_key": "AIXSOC-9"},
            index,
        )
        self.assertEqual(row["case_number"], "XSOC-JJNET-260724-001")
        self.assertEqual(row["case_ref"], "XSOC-JJNET-260724-001")


if __name__ == "__main__":
    unittest.main()
