"""Tests for Stellar case ID resolution during Jira writeback."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.stellar.writeback import resolve_stellar_case_id
from app.sync.state import SyncState


class TestResolveStellarCaseId(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = SyncState(Path(self.tmp.name) / "state.sqlite")
        self.state.init(legacy_source_id="stellar")
        self.state.record("stellar", "case-mapped", "AIXSOC-1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_uses_sqlite_mapping(self) -> None:
        cid = resolve_stellar_case_id(
            self.state,
            source_id="stellar",
            jira_key="AIXSOC-1",
        )
        self.assertEqual(cid, "case-mapped")

    def test_matching_override_allowed(self) -> None:
        cid = resolve_stellar_case_id(
            self.state,
            source_id="stellar",
            jira_key="AIXSOC-1",
            override_case_id="case-mapped",
        )
        self.assertEqual(cid, "case-mapped")

    def test_conflicting_override_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_stellar_case_id(
                self.state,
                source_id="stellar",
                jira_key="AIXSOC-1",
                override_case_id="other-case",
            )

    def test_untrusted_override_ignored(self) -> None:
        cid = resolve_stellar_case_id(
            self.state,
            source_id="stellar",
            jira_key="AIXSOC-99",
            override_case_id="attacker-case",
        )
        self.assertIsNone(cid)

    def test_description_fallback(self) -> None:
        case_from_desc = "abcdef0123456789abcdef01"
        fields = {
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": f"Stellar Case ID: {case_from_desc}"},
                        ],
                    }
                ],
            }
        }
        cid = resolve_stellar_case_id(
            self.state,
            source_id="stellar",
            jira_key="AIXSOC-2",
            jira_fields=fields,
        )
        self.assertEqual(cid, case_from_desc)


if __name__ == "__main__":
    unittest.main()
