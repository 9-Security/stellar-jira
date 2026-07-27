"""Tests for Stellar ingest response validation."""

from __future__ import annotations

import unittest

import httpx

from app.integrations.cycraft.stellar_ingest import stellar_ingest_succeeded


class StellarIngestTests(unittest.TestCase):
    def test_accepts_empty_200(self) -> None:
        response = httpx.Response(200, text="")
        self.assertTrue(stellar_ingest_succeeded(response))

    def test_rejects_error_json(self) -> None:
        response = httpx.Response(200, json={"error": "invalid payload"})
        self.assertFalse(stellar_ingest_succeeded(response))

    def test_rejects_http_500(self) -> None:
        response = httpx.Response(500, text="server error")
        self.assertFalse(stellar_ingest_succeeded(response))

    def test_accepts_success_flag(self) -> None:
        response = httpx.Response(200, json={"success": True})
        self.assertTrue(stellar_ingest_succeeded(response))


if __name__ == "__main__":
    unittest.main()
