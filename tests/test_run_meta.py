"""Tests for shared sync runner meta helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.sync.run_meta import (
    append_truncation_error,
    finalize_watermark_ms,
    note_watermark_mod,
    watermark_meta_key,
)
from app.sync.state import SyncState


class TestRunMeta(unittest.TestCase):
    def test_watermark_meta_key(self) -> None:
        self.assertEqual(watermark_meta_key("jj"), "last_max_mod_ms:jj")

    def test_note_watermark_mod(self) -> None:
        self.assertEqual(note_watermark_mod(100, 0), 100)
        self.assertEqual(note_watermark_mod(100, 150), 150)

    def test_finalize_watermark_ms_caps_failed(self) -> None:
        self.assertEqual(
            finalize_watermark_ms(500, failed_modified_at_ms=[300], existing_watermark_ms=400),
            299,
        )
        self.assertEqual(
            finalize_watermark_ms(0, failed_modified_at_ms=[300], existing_watermark_ms=500),
            299,
        )
        self.assertEqual(
            finalize_watermark_ms(200, failed_modified_at_ms=[], existing_watermark_ms=500),
            200,
        )

    def test_append_truncation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = SyncState(Path(tmp) / "t.sqlite")
            state.init()
            out: dict = {"ok": True, "errors": []}
            append_truncation_error(
                out,
                source_id="src",
                scope="cortex",
                max_pages=40,
                page_size_env_hint="SYNC_PAGE_SIZE",
            )
            self.assertTrue(out["truncated"])
            self.assertFalse(out["ok"])
            self.assertIn("SYNC_MAX_PAGES", out["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
