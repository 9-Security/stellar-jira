"""Multi-tenant scope tests for demo + admin APIs."""

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
from app.sync.case_snapshots import CaseSnapshotStore
from app.sync.state import SyncState


class TestMultiTenantDemo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.sync_db = root / "state.sqlite"
        self.platform_db = root / "platform.db"

        state = SyncState(self.sync_db)
        state.init(legacy_source_id="stellar")
        state.record(
            "stellar",
            "case-jjnet",
            "AIXSOC-100",
            tenant_source_id="jjnet",
            tenant_name="JJNET",
            customer_code="JJNET",
        )
        state.record(
            "stellar",
            "case-edr",
            "AIXSOC-200",
            tenant_source_id="jjnet-edr",
            tenant_name="JJNET-EDR",
            customer_code="JJEDR",
        )

        store = CaseSnapshotStore(self.sync_db)
        store.init()
        for case_id, code, cust in (
            ("case-jjnet", "AIXSOC-100", "JJNET"),
            ("case-edr", "AIXSOC-200", "JJEDR"),
        ):
            store.upsert_bundle(
                source_id="stellar",
                stellar_case_id=case_id,
                bundle={
                    "case": {
                        "_id": case_id,
                        "name": f"Case {code}",
                        "severity": "High",
                        "status": "New",
                        "created_at": 1783843071745,
                    },
                    "alerts": {"data": {"docs": []}},
                    "observables": {"observables": {"host": []}},
                },
                customer_code=cust,
                modified_at_ms=1000,
            )

        pstore = PlatformStore(self.platform_db)
        pstore.init()
        pstore.create_user(
            email="admin@demo.test",
            password_hash=hash_password("password123"),
            role="platform_admin",
            totp_policy="off",
        )
        pstore.create_user(
            email="viewer@jjnet.test",
            password_hash=hash_password("password123"),
            role="tenant_viewer",
            tenant_source_id="jjnet",
            totp_policy="off",
        )
        pstore.create_user(
            email="tadmin@jjnet.test",
            password_hash=hash_password("password123"),
            role="tenant_admin",
            tenant_source_id="jjnet",
            totp_policy="off",
        )

        self.platform_settings = PlatformSettings(
            platform_enabled=True,
            platform_db_path=str(self.platform_db),
            platform_secret_key="test-secret-key-for-jwt-signing-32",
            platform_bootstrap_allow_password_only=True,
            platform_cookie_secure=False,
        )
        self.stellar_settings = StellarSettings(
            stellar_sync_state_db=str(self.sync_db),
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
            "app.routers.demo.get_stellar_settings",
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

    def test_platform_admin_tenant_filter(self) -> None:
        self._login()
        r_all = self.client.get("/v1/demo/overview?source=sync&window=all")
        self.assertEqual(r_all.status_code, 200)
        self.assertEqual(r_all.json()["summary"]["total_cases"], 2)

        r_jjnet = self.client.get(
            "/v1/demo/overview?source=sync&window=all&tenant=jjnet"
        )
        self.assertEqual(r_jjnet.status_code, 200)
        self.assertEqual(r_jjnet.json()["summary"]["total_cases"], 1)

    def test_tenant_viewer_isolation(self) -> None:
        self._login("viewer@jjnet.test")
        r = self.client.get("/v1/demo/overview?source=sync&window=all")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["summary"]["total_cases"], 1)

        r_forbidden = self.client.get(
            "/v1/demo/overview?source=sync&window=all&tenant=jjnet-edr"
        )
        self.assertEqual(r_forbidden.status_code, 403)

    def test_tenants_list_scope(self) -> None:
        self._login("viewer@jjnet.test")
        r = self.client.get("/v1/demo/tenants")
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["source_id"], "jjnet")

        self._login()
        r_all = self.client.get("/v1/demo/tenants")
        self.assertGreaterEqual(len(r_all.json()["data"]), 2)

    def test_tenant_admin_user_crud_scope(self) -> None:
        self._login("tadmin@jjnet.test")
        r_list = self.client.get("/v1/admin/users")
        self.assertEqual(r_list.status_code, 200)
        emails = {u["email"] for u in r_list.json()["data"]}
        self.assertIn("viewer@jjnet.test", emails)
        self.assertNotIn("admin@demo.test", emails)

        r_create = self.client.post(
            "/v1/admin/users",
            json={
                "email": "newviewer@jjnet.test",
                "password": "password123",
                "role": "tenant_viewer",
                "totp_policy": "off",
            },
        )
        self.assertEqual(r_create.status_code, 200, r_create.text)
        self.assertEqual(r_create.json()["data"]["tenant_source_id"], "jjnet")

        r_bad_role = self.client.post(
            "/v1/admin/users",
            json={
                "email": "bad@jjnet.test",
                "password": "password123",
                "role": "soc_analyst",
                "totp_policy": "off",
            },
        )
        self.assertEqual(r_bad_role.status_code, 400)

    def test_tenant_viewer_cases_list_isolation(self) -> None:
        self._login("viewer@jjnet.test")
        r = self.client.get("/v1/demo/cases")
        self.assertEqual(r.status_code, 200, r.text)
        rows = r.json()["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["jira_key"], "AIXSOC-100")

    def test_tenant_viewer_case_detail_cross_tenant(self) -> None:
        self._login("viewer@jjnet.test")
        r_ok = self.client.get("/v1/demo/cases/AIXSOC-100")
        self.assertEqual(r_ok.status_code, 200, r_ok.text)

        r_other = self.client.get("/v1/demo/cases/AIXSOC-200")
        self.assertEqual(r_other.status_code, 404)

    def test_platform_admin_case_detail_tenant_filter(self) -> None:
        self._login()
        r_all = self.client.get("/v1/demo/cases/AIXSOC-200")
        self.assertEqual(r_all.status_code, 200)

        r_filtered = self.client.get("/v1/demo/cases/AIXSOC-200?tenant=jjnet")
        self.assertEqual(r_filtered.status_code, 404)

        r_match = self.client.get("/v1/demo/cases/AIXSOC-100?tenant=jjnet")
        self.assertEqual(r_match.status_code, 200)


if __name__ == "__main__":
    unittest.main()
