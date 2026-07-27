"""Tests for platform auth API (P0)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import PlatformSettings, get_platform_settings
from app.main import app
from app.platform.deps import get_platform_store
from app.platform.security import hash_password
from app.platform.store import PlatformStore
from app.routers.platform_auth import _settings


def _totp_secret_from_uri(uri: str) -> str:
    return parse_qs(urlparse(uri).query)["secret"][0]


class TestPlatformAuth(unittest.TestCase):
    def setUp(self) -> None:
        import os

        os.environ["PLATFORM_PUBLIC_EXPOSURE"] = "false"
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "platform.db"
        self.settings = PlatformSettings(
            platform_enabled=True,
            platform_db_path=str(self.db),
            platform_secret_key="test-secret-key-for-jwt-signing-32chars",
            platform_require_totp=True,
            platform_bootstrap_allow_password_only=True,
            platform_public_exposure=False,
            platform_cookie_secure=False,
        )
        store = PlatformStore(self.db)
        store.init()
        store.create_user(
            email="admin@example.com",
            password_hash=hash_password("password123"),
            role="platform_admin",
        )
        store.create_user(
            email="viewer@client.com",
            password_hash=hash_password("password123"),
            role="tenant_viewer",
            tenant_source_id="jjnet",
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

    def test_login_sets_session_cookie(self) -> None:
        r = self.client.post(
            "/v1/auth/login",
            json={"email": "admin@example.com", "password": "password123"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body.get("totp_setup_required"))
        self.assertIsNone(body.get("access_token"))
        self.assertIn(self.settings.platform_session_cookie_name, r.cookies)
        me = self.client.get("/v1/auth/me")
        self.assertEqual(me.status_code, 200)

    def test_login_required_policy_bootstrap(self) -> None:
        store = PlatformStore(self.db)
        user = store.get_user_by_email("admin@example.com")
        assert user is not None
        store.update_user(user["id"], totp_policy="required")
        r = self.client.post(
            "/v1/auth/login",
            json={"email": "admin@example.com", "password": "password123"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("totp_setup_required"))

    def test_me_requires_token(self) -> None:
        r = self.client.get("/v1/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_totp_setup_and_confirm_flow(self) -> None:
        login = self.client.post(
            "/v1/auth/login",
            json={"email": "admin@example.com", "password": "password123"},
        )
        self.assertEqual(login.status_code, 200)
        setup = self.client.post("/v1/auth/totp/setup")
        self.assertEqual(setup.status_code, 200)
        secret = _totp_secret_from_uri(setup.json()["provisioning_uri"])
        import pyotp

        code = pyotp.TOTP(secret).now()
        confirm = self.client.post(
            "/v1/auth/totp/confirm",
            json={"code": code},
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertFalse(confirm.json().get("totp_setup_required"))
        me = self.client.get("/v1/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json().get("totp_enabled"))

    def test_login_with_totp_required(self) -> None:
        store = PlatformStore(self.db)
        user = store.get_user_by_email("admin@example.com")
        assert user is not None
        import pyotp

        secret = pyotp.random_base32()
        store.set_totp_secret(user["id"], secret, enabled=True)
        step1 = self.client.post(
            "/v1/auth/login",
            json={"email": "admin@example.com", "password": "password123"},
        )
        self.assertEqual(step1.status_code, 200)
        self.assertTrue(step1.json().get("requires_totp"))
        login_token = step1.json()["login_token"]
        code = pyotp.TOTP(secret).now()
        step2 = self.client.post(
            "/v1/auth/totp/verify",
            json={"login_token": login_token, "code": code},
        )
        self.assertEqual(step2.status_code, 200)
        self.assertIn(self.settings.platform_session_cookie_name, step2.cookies)
        me = self.client.get("/v1/auth/me")
        self.assertEqual(me.status_code, 200)

    def test_logout_clears_session(self) -> None:
        self.client.post(
            "/v1/auth/login",
            json={"email": "admin@example.com", "password": "password123"},
        )
        logout = self.client.post("/v1/auth/logout")
        self.assertEqual(logout.status_code, 200)
        me = self.client.get("/v1/auth/me")
        self.assertEqual(me.status_code, 401)

    def test_tenant_user_login(self) -> None:
        r = self.client.post(
            "/v1/auth/login",
            json={"email": "viewer@client.com", "password": "password123"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["tenant_source_id"], "jjnet")

    def test_invalid_login(self) -> None:
        r = self.client.post(
            "/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong"},
        )
        self.assertEqual(r.status_code, 401)

    def test_auth_health_minimal(self) -> None:
        r = self.client.get("/v1/auth/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body, {"status": "ok"})
        self.assertNotIn("db_path", body)

    def test_login_rate_limited(self) -> None:
        from app.platform.rate_limit import _login_limiter

        _login_limiter.reset()
        limited = self.settings.model_copy(
            update={
                "platform_login_rate_limit_attempts": 2,
                "platform_login_rate_limit_window_seconds": 300,
            }
        )
        app.dependency_overrides[_settings] = lambda: limited
        app.dependency_overrides[get_platform_settings] = lambda: limited
        try:
            for _ in range(2):
                self.client.post(
                    "/v1/auth/login",
                    json={"email": "nobody@example.com", "password": "bad"},
                )
            blocked = self.client.post(
                "/v1/auth/login",
                json={"email": "nobody@example.com", "password": "bad"},
            )
            self.assertEqual(blocked.status_code, 429)
        finally:
            _login_limiter.reset()
            app.dependency_overrides[_settings] = lambda: self.settings
            app.dependency_overrides[get_platform_settings] = lambda: self.settings


if __name__ == "__main__":
    unittest.main()
