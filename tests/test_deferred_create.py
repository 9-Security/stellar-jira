"""Deferred create queue for failed create / decision defer (not severity gating)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.sync.state import SyncState


class TestDeferredCreate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = SyncState(Path(self.tmp.name) / "test.sqlite")
        self.state.init(legacy_source_id="stellar")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_add_list_remove(self) -> None:
        self.state.add_deferred_create("stellar", "case-a")
        self.state.add_deferred_create("stellar", "case-b")
        self.assertEqual(self.state.list_deferred_create("stellar"), ["case-a", "case-b"])
        self.state.remove_deferred_create("stellar", "case-a")
        self.assertEqual(self.state.list_deferred_create("stellar"), ["case-b"])
        self.state.remove_deferred_create("stellar", "case-b")
        self.assertEqual(self.state.list_deferred_create("stellar"), [])


class TestInjectDeferredSkipsSeverity(unittest.IsolatedAsyncioTestCase):
    async def test_prunes_low_medium_from_deferred_queue(self) -> None:
        from app.stellar_sync.runner import _inject_deferred_cases

        tmp = tempfile.TemporaryDirectory()
        try:
            state = SyncState(Path(tmp.name) / "t.sqlite")
            state.init(legacy_source_id="stellar")
            state.add_deferred_create("stellar", "low-1")
            state.add_deferred_create("stellar", "high-1")

            client = MagicMock()
            client.extract_case_one = MagicMock(
                side_effect=lambda raw: raw.get("data") if isinstance(raw, dict) else raw
            )

            async def get_case(cid: str):
                if cid == "low-1":
                    return {"data": {"_id": "low-1", "severity": "Low", "modified_at": 1}}
                return {"data": {"_id": "high-1", "severity": "High", "modified_at": 2}}

            client.get_case = AsyncMock(side_effect=get_case)

            merged = await _inject_deferred_cases(
                [],
                source_id="stellar",
                state=state,
                client=client,
                dry_run=False,
                allowed_severities=frozenset({"Critical", "High"}),
            )
            self.assertEqual([c["_id"] for c in merged], ["high-1"])
            self.assertEqual(state.list_deferred_create("stellar"), ["high-1"])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
