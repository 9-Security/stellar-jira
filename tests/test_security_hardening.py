"""Security hardening tests (public exposure, SPA routing)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import PlatformSettings, get_platform_settings
from app.main import app
from app.platform.deps import get_platform_store
from app.platform.security import hash_password
from app.platform.store import PlatformStore
from app.routers.platform_auth import _settings
from app.spa_static import SPAStaticFiles


class TestSPAStaticSecurity(unittest.TestCase):
    def test_api_path_not_spa_fallback(self) -> None:
        dist = Path(__file__).resolve().parents[1] / "web" / "dist"
        if not dist.is_dir():
            self.skipTest("web/dist not built")
        mini = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        mini.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="ui")
        client = TestClient(mini)
        r = client.get("/v1/no-such-route")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("<html", r.text.lower())

        r_ui = client.get("/settings/integrations")
        self.assertEqual(r_ui.status_code, 200)
        self.assertIn("<html", r_ui.text.lower())


class TestPublicExposureBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "platform.db"
        store = PlatformStore(self.db)
        store.init()
        store.create_user(
            email="new@example.com",
            password_hash=hash_password("password123"),
            role="platform_admin",
            totp_policy="required",
        )
        self.settings = PlatformSettings(
            platform_enabled=True,
            platform_db_path=str(self.db),
            platform_secret_key="test-secret-key-for-jwt-signing-32chars",
            platform_require_totp=True,
            platform_bootstrap_allow_password_only=True,
            platform_public_exposure=True,
            platform_cookie_secure=False,
        )

        def _test_store() -> PlatformStore:
            s = PlatformStore(self.db)
            s.init()
            return s

        app.dependency_overrides[get_platform_store] = _test_store
        app.dependency_overrides[_settings] = lambda: self.settings
        app.dependency_overrides[get_platform_settings] = lambda: self.settings
        self.client = TestClient(app)

    def tearDown(self) -> None:
        from app.platform.rate_limit import reset_login_rate_limiter

        reset_login_rate_limiter()
        app.dependency_overrides.clear()
        self.tmp.cleanup()

    def test_bootstrap_login_blocked_when_public(self) -> None:
        r = self.client.post(
            "/v1/auth/login",
            json={"email": "new@example.com", "password": "password123"},
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertIn("TOTP setup required", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
