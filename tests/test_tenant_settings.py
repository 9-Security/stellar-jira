"""Tests for tenant-scoped settings integrations API."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import PlatformSettings, StellarSettings, get_platform_settings
from app.main import app
from app.platform.deps import get_platform_store
from app.platform.security import hash_password
from app.platform.store import PlatformStore
from app.routers.platform_auth import _settings


class TestTenantSettingsIntegrations(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.platform_db = root / "platform.db"

        pstore = PlatformStore(self.platform_db)
        pstore.init()
        pstore.create_user(
            email="admin@demo.test",
            password_hash=hash_password("password123"),
            role="platform_admin",
            totp_policy="off",
        )
        pstore.create_user(
            email="jjnet@demo.test",
            password_hash=hash_password("password123"),
            role="tenant_admin",
            totp_policy="off",
            tenant_source_id="jjnet",
        )
        pstore.create_user(
            email="viewer@demo.test",
            password_hash=hash_password("password123"),
            role="tenant_viewer",
            totp_policy="off",
            tenant_source_id="jjnet",
        )
        pstore.set_cycraft_enabled("jjnet", enabled=True, updated_by_user_id="x")

        self.platform_settings = PlatformSettings(
            platform_enabled=True,
            platform_db_path=str(self.platform_db),
            platform_secret_key="test-secret-key-for-jwt-signing-32",
            platform_bootstrap_allow_password_only=True,
            platform_cookie_secure=False,
        )
        self.stellar_settings = StellarSettings(
            stellar_sync_state_db=str(root / "state.sqlite"),
            stellar_poll_source_id="stellar",
        )

        def _test_store() -> PlatformStore:
            s = PlatformStore(self.platform_db)
            s.init()
            return s

        app.dependency_overrides[get_platform_store] = _test_store
        app.dependency_overrides[_settings] = lambda: self.platform_settings
        app.dependency_overrides[get_platform_settings] = lambda: self.platform_settings
        self.client = TestClient(app)
        self._stellar_patch = patch(
            "app.routers.tenant_settings.get_stellar_settings",
            return_value=self.stellar_settings,
        )
        self._stellar_patch.start()

    def tearDown(self) -> None:
        from app.platform.rate_limit import reset_login_rate_limiter

        reset_login_rate_limiter()
        self._stellar_patch.stop()
        app.dependency_overrides.clear()
        self.tmp.cleanup()

    def _login(self, email: str = "admin@demo.test") -> None:
        r = self.client.post(
            "/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def test_list_integrations_platform_admin(self) -> None:
        self._login()
        r = self.client.get("/v1/settings/integrations")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["meta"]["scope"], "tenant")
        jjnet = next(
            (row for row in body["data"] if row["tenant_source_id"] == "jjnet"),
            None,
        )
        self.assertIsNotNone(jjnet)
        assert jjnet is not None
        self.assertTrue(jjnet["integrations"]["cycraft"]["enabled"])
        self.assertEqual(jjnet["integrations"]["cycraft"]["connector_type"], "cycraft")

    def test_save_secrets_to_db(self) -> None:
        self._login()
        r = self.client.patch(
            "/v1/settings/integrations/jjnet",
            json={
                "enabled": True,
                "xcockpit_customer_key": "cust-1",
                "stellar_xdr_ingest_path": "/webhook/in",
                "xcockpit_api_key": "xc-key",
                "stellar_xdr_api_key": "xdr-key",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        cycraft = r.json()["data"]["integrations"]["cycraft"]
        self.assertTrue(cycraft["secrets"]["xcockpit_api_key"])
        self.assertTrue(cycraft["secrets"]["stellar_xdr_api_key"])

    def test_patch_disable_cycraft(self) -> None:
        self._login()
        r = self.client.patch(
            "/v1/settings/integrations/jjnet",
            json={"enabled": False},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["data"]["integrations"]["cycraft"]["enabled"])

    def test_patch_tenant_config_fields(self) -> None:
        self._login()
        r = self.client.patch(
            "/v1/settings/integrations/jjnet",
            json={
                "stellar_xdr_ingest_path": "/webhook/test/ingest",
                "xcockpit_customer_key": "cust-uuid",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        cycraft = r.json()["data"]["integrations"]["cycraft"]
        self.assertEqual(cycraft["stellar_xdr_ingest_path"], "/webhook/test/ingest")
        self.assertEqual(cycraft["xcockpit_customer_key"], "cust-uuid")

    def test_tenant_admin_sees_only_own_tenant(self) -> None:
        self._login("jjnet@demo.test")
        r = self.client.get("/v1/settings/integrations")
        self.assertEqual(r.status_code, 200, r.text)
        ids = {row["tenant_source_id"] for row in r.json()["data"]}
        self.assertEqual(ids, {"jjnet"})

    def test_tenant_admin_cannot_patch_other_tenant(self) -> None:
        self._login("jjnet@demo.test")
        r = self.client.patch(
            "/v1/settings/integrations/jjnet-edr",
            json={"enabled": True},
        )
        self.assertEqual(r.status_code, 403, r.text)

    def test_tenant_viewer_denied(self) -> None:
        self._login("viewer@demo.test")
        r = self.client.get("/v1/settings/integrations")
        self.assertEqual(r.status_code, 403, r.text)


if __name__ == "__main__":
    unittest.main()
