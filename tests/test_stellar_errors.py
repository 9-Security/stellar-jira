"""Tests for Stellar HTTP error helpers."""

from __future__ import annotations

import unittest

import httpx

from app.stellar.errors import StellarAPIError, infer_error_type
from app.stellar.http_errors import inbound_stellar_unreachable, stellar_error_dict, wrap_transport_error


class TestStellarErrors(unittest.TestCase):
    def test_infer_timeout(self) -> None:
        self.assertEqual(infer_error_type(status_code=None, message="timeout after 30s"), "timeout")

    def test_infer_5xx(self) -> None:
        self.assertEqual(infer_error_type(status_code=500, message="err"), "http_5xx")

    def test_wrap_timeout(self) -> None:
        exc = wrap_transport_error(
            httpx.ReadTimeout("t"),
            method="GET",
            path="cases",
            timeout_seconds=30.0,
        )
        self.assertIsInstance(exc, StellarAPIError)
        self.assertEqual(exc.error_type, "timeout")

    def test_stellar_error_dict(self) -> None:
        err = StellarAPIError("boom", status_code=500, error_type="http_5xx")
        d = stellar_error_dict(err, source_id="stellar")
        self.assertEqual(d["error_type"], "http_5xx")
        self.assertEqual(d["http_status"], 500)

    def test_inbound_unreachable(self) -> None:
        self.assertTrue(
            inbound_stellar_unreachable(
                {"ok": False, "errors": [{"scope": "stellar", "error_type": "timeout"}]}
            )
        )
        self.assertFalse(inbound_stellar_unreachable({"ok": True, "fetched": 1}))


if __name__ == "__main__":
    unittest.main()
