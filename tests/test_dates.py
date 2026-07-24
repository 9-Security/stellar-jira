"""Tests for shared date helpers."""

from __future__ import annotations

import unittest

from app.dates import format_detection_time


class TestFormatDetectionTime(unittest.TestCase):
    def test_formats_in_taipei(self) -> None:
        # 1780000000000 ms → fixed string in Asia/Taipei
        out = format_detection_time(1780000000000, timezone_name="Asia/Taipei")
        self.assertRegex(out, r"^[A-Z][a-z]{2} \d{1,2}(st|nd|rd|th) \d{4} \d{2}:\d{2}:\d{2}$")


if __name__ == "__main__":
    unittest.main()
