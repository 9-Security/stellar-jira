"""Tests for CyCraft connection probe (no POST to auth webhook)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.integrations.cycraft.config import Settings
from app.integrations.cycraft.test_connection import test_cycraft_connection


class TestCycraftTestConnection(unittest.TestCase):
    def test_stellar_probe_uses_options_not_post(self) -> None:
        settings = Settings(
            STELLAR_BASE_URL="https://soc.example.test",
            STELLAR_XDR_API_KEY="secret",
            STELLAR_XDR_AUTH_PATH="/webhook/auth",
            CONNECTOR_HTTP_TIMEOUT_SECONDS=5,
            CONNECTOR_TLS_VERIFY=True,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.integrations.cycraft.test_connection.httpx.AsyncClient",
            return_value=mock_http,
        ):
            with patch(
                "app.integrations.cycraft.test_connection.XCockpitClient",
            ) as mock_xc:
                xc = mock_xc.return_value
                xc.default_created_after = MagicMock()
                xc.fetch_alert_items = AsyncMock(return_value=[])
                xc.aclose = AsyncMock()

                out = asyncio.run(test_cycraft_connection(settings))

        self.assertTrue(out["xcockpit"]["ok"])
        self.assertFalse(out["stellar_xdr"]["skipped"])
        mock_http.request.assert_awaited_once()
        call_kwargs = mock_http.request.await_args
        self.assertEqual(call_kwargs.args[0], "OPTIONS")
        self.assertNotEqual(call_kwargs.args[0], "POST")


class TestPlatformGate(unittest.TestCase):
    def test_disabled_platform_returns_false(self) -> None:
        from app.integrations.cycraft.platform_gate import any_tenant_cycraft_enabled

        with patch("app.integrations.cycraft.platform_gate.get_platform_settings") as gp:
            gp.return_value.platform_enabled = False
            self.assertFalse(any_tenant_cycraft_enabled())


if __name__ == "__main__":
    unittest.main()
