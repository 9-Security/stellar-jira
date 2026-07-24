"""Tests for demo dashboard API (real sync DB fixture)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import PlatformSettings, StellarSettings
from app.main import app
from app.platform.deps import get_platform_store
from app.platform.security import hash_password
from app.platform.store import PlatformStore
from app.routers.platform_auth import _settings
from app.sync.case_snapshots import CaseSnapshotStore
from app.sync.state import SyncState
from app.config import get_platform_settings


class TestDemoApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.sync_db = root / "state.sqlite"
        self.platform_db = root / "platform.db"

        state = SyncState(self.sync_db)
        state.init(legacy_source_id="stellar")
        state.record(
            "stellar",
            "case-demo-1",
            "AIXSOC-100",
            tenant_source_id="jjnet",
            tenant_name="JJNET",
            customer_code="JJNET",
        )
        store = CaseSnapshotStore(self.sync_db)
        store.init()
        store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="case-demo-1",
            bundle={
                "case": {
                    "_id": "case-demo-1",
                    "name": "Demo malware case",
                    "severity": "High",
                    "status": "New",
                    "created_at": 1783843071745,
                },
                "alerts": {"data": {"docs": []}},
                "observables": {
                    "observables": {
                        "host": [
                            {"hostname": "PC-01", "ip": "10.0.0.5"},
                        ]
                    }
                },
            },
            customer_code="JJNET",
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
        from app.config import get_platform_settings as gps

        app.dependency_overrides[gps] = lambda: self.platform_settings
        self.client = TestClient(app)
        self._stellar_patch = patch(
            "app.routers.demo.get_stellar_settings",
            return_value=self.stellar_settings,
        )
        self._stellar_patch.start()

    def tearDown(self) -> None:
        self._stellar_patch.stop()
        app.dependency_overrides.clear()
        self.tmp.cleanup()

    def _login(self) -> None:
        r = self.client.post(
            "/v1/auth/login",
            json={"email": "admin@demo.test", "password": "password123"},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def test_overview_real_data(self) -> None:
        self._login()
        r = self.client.get("/v1/demo/overview?source=sync&window=all")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["summary"]["total_cases"], 1)
        self.assertEqual(body["summary"]["open_cases"], 1)
        self.assertIn("new_in_window", body["summary"])
        self.assertEqual(body["meta"]["source"], "sync_db")
        self.assertEqual(body["meta"]["window"], "all")
        recent = body["recent_cases"][0]
        self.assertEqual(recent["case_number"], "AIXSOC-100")

    def test_overview_link_without_snapshot(self) -> None:
        state = SyncState(self.sync_db)
        state.record(
            "stellar",
            "case-no-snapshot",
            "AIXSOC-200",
            tenant_source_id="jjnet",
            tenant_name="JJNET",
            customer_code="JJNET",
        )
        self._login()
        r = self.client.get("/v1/demo/overview?source=sync&window=all")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["summary"]["total_cases"], 2)

    def test_case_detail_hosts(self) -> None:
        self._login()
        r = self.client.get("/v1/demo/cases/AIXSOC-100")
        self.assertEqual(r.status_code, 200, r.text)
        hosts = r.json()["data"]["affected_hosts"]
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["hostname"], "PC-01")


if __name__ == "__main__":
    unittest.main()
