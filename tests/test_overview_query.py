"""Tests for overview query parsing."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.demo.overview_query import parse_overview_query


class TestOverviewQuery(unittest.TestCase):
    def test_defaults_12h(self) -> None:
        q = parse_overview_query()
        self.assertEqual(q.window, "12h")
        self.assertEqual(q.scope, "modified")
        self.assertEqual(q.new_basis, "created")
        self.assertIsNotNone(q.since_ms)

    def test_all_window_no_since(self) -> None:
        q = parse_overview_query(window="all")
        self.assertIsNone(q.since_ms)
        self.assertIsNone(q.since_iso)

    def test_invalid_window(self) -> None:
        with self.assertRaises(ValueError):
            parse_overview_query(window="3d")

    def test_since_ms_roughly_12h_ago(self) -> None:
        before = datetime.now(timezone.utc) - timedelta(hours=12, minutes=1)
        q = parse_overview_query(window="12h")
        assert q.since_ms is not None
        since = datetime.fromtimestamp(q.since_ms / 1000, tz=timezone.utc)
        self.assertGreater(since, before)


if __name__ == "__main__":
    unittest.main()
