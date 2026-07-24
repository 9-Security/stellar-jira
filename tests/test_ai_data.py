"""Tests for read-only /v1/ai-data case endpoints."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import StellarSettings
from app.main import app
from app.sync.case_snapshots import CaseSnapshotStore
from app.sync.state import SyncState


class TestAiDataRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.sqlite"
        state = SyncState(self.db)
        state.init(legacy_source_id="stellar")
        state.record(
            "stellar",
            "case-1",
            "AIXSOC-99",
            tenant_source_id="tenant-a",
            tenant_name="Tenant A",
            customer_code="TA",
        )
        store = CaseSnapshotStore(self.db)
        store.init()
        store.upsert_bundle(
            source_id="stellar",
            stellar_case_id="case-1",
            bundle={
                "case": {"_id": "case-1", "name": "Test case", "severity": "High"},
                "alerts": {"data": {"docs": [{"_id": "a1"}, {"_id": "a2"}]}},
                "observables": {"host": []},
                "summary": {"data": {}},
                "activities": [],
                "ai_summary": {"status": "ready"},
            },
            customer_code="TA",
            modified_at_ms=1000,
        )
        self.settings = StellarSettings(
            stellar_sync_state_db=str(self.db),
            stellar_poll_source_id="stellar",
            ai_data_api_token="test-ai-token",
        )
        self.auth = {"Authorization": "Bearer test-ai-token"}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_and_get_case_on_loopback(self) -> None:
        with patch("app.routers.ai_data.get_stellar_settings", return_value=self.settings):
            client = TestClient(app)
            listed = client.get("/v1/ai-data/cases", headers=self.auth)
            self.assertEqual(listed.status_code, 200)
            body = listed.json()
            self.assertEqual(body["pagination"]["total"], 1)
            self.assertEqual(body["data"][0]["jira_key"], "AIXSOC-99")
            self.assertEqual(body["data"][0]["stellar_case_id"], "case-1")

            detail = client.get("/v1/ai-data/cases/AIXSOC-99", headers=self.auth)
            self.assertEqual(detail.status_code, 200)
            data = detail.json()["data"]
            self.assertEqual(data["case"]["name"], "Test case")
            self.assertEqual(data["ai_summary"]["status"], "ready")

            alerts = client.get(
                "/v1/ai-data/cases/AIXSOC-99/alerts?limit=1",
                headers=self.auth,
            )
            self.assertEqual(alerts.status_code, 200)
            alert_body = alerts.json()
            self.assertEqual(alert_body["pagination"]["total"], 2)
            self.assertEqual(len(alert_body["data"]), 1)
            self.assertEqual(alert_body["data"][0]["_id"], "a1")

    def test_token_required_when_configured(self) -> None:
        settings = StellarSettings(
            stellar_sync_state_db=str(self.db),
            stellar_poll_source_id="stellar",
            ai_data_api_token="secret-ai",
        )
        with patch("app.routers.ai_data.get_stellar_settings", return_value=settings):
            client = TestClient(app)
            denied = client.get("/v1/ai-data/cases")
            self.assertEqual(denied.status_code, 403)
            ok = client.get(
                "/v1/ai-data/cases",
                headers={"Authorization": "Bearer secret-ai"},
            )
            self.assertEqual(ok.status_code, 200)

    def test_unconfigured_token_returns_503(self) -> None:
        settings = StellarSettings(
            stellar_sync_state_db=str(self.db),
            stellar_poll_source_id="stellar",
            ai_data_api_token=None,
        )
        with patch("app.routers.ai_data.get_stellar_settings", return_value=settings):
            client = TestClient(app)
            resp = client.get("/v1/ai-data/cases")
            self.assertEqual(resp.status_code, 503)

    def test_unknown_include_rejected(self) -> None:
        with patch("app.routers.ai_data.get_stellar_settings", return_value=self.settings):
            client = TestClient(app)
            resp = client.get(
                "/v1/ai-data/cases/AIXSOC-99?include=case,nope",
                headers=self.auth,
            )
            self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
