from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import NotifySettings, StellarSettings
from app.sync.state import SyncState
from app.stellar_sync.runner import (
    _apply_cases_to_jira,
    _maybe_severity_escalation_refresh,
    _reconcile_pending_jira,
)


class TestMultiTenantRunnerSafety(unittest.IsolatedAsyncioTestCase):
    async def test_apply_cases_reads_module_notify_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            state = SyncState(Path(tmp) / "state.sqlite")
            state.init()
            with patch(
                "app.stellar_sync.runner.get_notify_settings",
                return_value=NotifySettings(
                    line_notify_enabled=False,
                    maiagent_all_cases_enabled=False,
                ),
            ):
                result = await _apply_cases_to_jira(
                    [],
                    source_id="stellar",
                    window_start_ms=0,
                    state=state,
                    st=StellarSettings(
                        decision_enabled=False,
                        case_archive_enabled=False,
                        case_archive_on_severity_escalation=False,
                    ),
                    dry_run=True,
                    jira=None,
                    client=MagicMock(),
                    update_watermark=False,
                )

        self.assertTrue(result["ok"])

    async def test_escalation_uses_registry_customer_code(self) -> None:
        snapshot_store = MagicMock()
        snapshot_store.get_latest.return_value = {"snapshot_id": "old"}
        snapshot_store.load_bundle_payload.return_value = {
            "case": {"severity": "Medium"}
        }
        client = MagicMock()
        client.fetch_case_bundle = AsyncMock(
            return_value={
                "case": {
                    "_id": "case-1",
                    "severity": "High",
                    "tenant_name": "JJNET-EDR",
                }
            }
        )
        decision = MagicMock(
            action="escalate",
            escalation="L2",
            playbook_id="PB-1",
            rule_hits=[],
        )
        refreshed: list[dict] = []

        with patch(
            "app.stellar_sync.runner.archive_stellar_bundle",
            new=AsyncMock(return_value="snapshot-new"),
        ) as archive:
            with patch(
                "app.stellar_sync.runner.evaluate_case_decision",
                new=AsyncMock(return_value=decision),
            ) as evaluate:
                await _maybe_severity_escalation_refresh(
                    st=StellarSettings(
                        decision_enabled=True,
                        decision_only_without_cortex_case_id=False,
                    ),
                    client=client,
                    case={
                        "_id": "case-1",
                        "severity": "High",
                        "tenant_name": "JJNET-EDR",
                    },
                    source_id="stellar",
                    customer_code="JJEDR",
                    jira_key="AIXSOC-1",
                    snapshot_store=snapshot_store,
                    decision_store=MagicMock(),
                    refreshed=refreshed,
                )

        self.assertEqual(archive.await_args.kwargs["customer_code"], "JJEDR")
        self.assertEqual(evaluate.await_args.kwargs["customer_code"], "JJEDR")

    async def test_pending_reconcile_uses_tenant_project(self) -> None:
        jira = MagicMock()
        jira.find_issue_key_for_stellar_case = AsyncMock(
            return_value="TENANTPROJ-10"
        )

        result = await _reconcile_pending_jira(
            jira,
            project_key="TENANTPROJ",
            source_id="stellar",
            case_id="case-10",
        )

        self.assertEqual(result, "TENANTPROJ-10")
        jira.find_issue_key_for_stellar_case.assert_awaited_once_with(
            "TENANTPROJ",
            "case-10",
        )


if __name__ == "__main__":
    unittest.main()
