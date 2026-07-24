"""SPA static file serving tests."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class TestSpaStatic(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_spa_routes_return_index_html(self) -> None:
        for path in ("/login", "/cases", "/settings/users", "/cases/AIXSOC-1"):
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertIn("text/html", resp.headers.get("content-type", ""))
                self.assertIn("id=\"root\"", resp.text)

    def test_root_returns_index_html(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
