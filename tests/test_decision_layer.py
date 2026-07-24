"""Tests for AIxSOC Decision Layer (rules, knowledge, store, outcome, report)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import NotifySettings
from app.decision.actions import apply_decision_to_jira_fields, should_create_ticket
from app.decision.knowledge import enrich_knowledge, match_sigma_catalogue, resolve_asset_criticality
from app.decision.models import DecisionResult
from app.decision.outcome import infer_outcome_from_text, apply_outcome_from_jira
from app.decision.pipeline import evaluate_case_decision
from app.decision.report import compute_decision_metrics, build_pilot_report, render_pilot_markdown
from app.decision.rules import apply_rules, load_decision_rules
from app.decision.store import DecisionStore


def _malware_bundle() -> dict:
    return {
        "alerts": {
            "data": {
                "docs": [
                    {
                        "_source": {
                            "name": "WildFire Malware",
                            "palo_alto_networks": {
                                "category": "Malware",
                                "name": "WildFire Malware",
                                "description": "Suspicious executable detected by WildFire",
                                "action_pretty": "Detected",
                            },
                        }
                    }
                ]
            }
        },
        "summary": {"data": {"tactics": ["Malware", "Execution"], "techniques": ["T1204"]}},
        "observables": {
            "observables": {
                "host": [{"hostname": "dc01", "ip": "10.0.0.1"}],
                "user": [{"username": "admin"}],
            }
        },
    }


class TestDecisionRules(unittest.TestCase):
    def test_load_shipped_rules(self) -> None:
        doc = load_decision_rules()
        self.assertTrue(doc.get("rules"))
        self.assertEqual(doc.get("version"), "1.1")

    def test_low_defers(self) -> None:
        decision = apply_rules(
            case={"_id": "c1", "severity": "Low", "name": "Noise"},
            bundle={},
            customer_code="JJ",
        )
        self.assertEqual(decision.action, "defer")
        self.assertIn("sev_low_defer", decision.rule_hits)
        self.assertFalse(should_create_ticket(decision))

    def test_malware_escalates_ir(self) -> None:
        decision = apply_rules(
            case={"_id": "c2", "severity": "Critical", "name": "WildFire Malware"},
            bundle=_malware_bundle(),
            customer_code="JJ",
        )
        self.assertEqual(decision.action, "escalate")
        self.assertEqual(decision.escalation, "IR")
        self.assertTrue(decision.notify_customer)
        self.assertTrue(decision.isolate_host)
        self.assertIn("malware_critical_ir", decision.rule_hits)

    def test_malware_already_blocked_no_reisolate(self) -> None:
        """Case 1220-style: Malware + Prevented → IR review, isolate_host false."""
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Persistence",
                                    "action_pretty": "Detected",
                                }
                            }
                        },
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Malware",
                                    "name": "WildFire Malware",
                                    "action_pretty": "Prevented (Blocked)",
                                    "case_id": 3363,
                                }
                            }
                        },
                    ]
                }
            }
        }
        decision = apply_rules(
            case={"_id": "c1220", "severity": "Critical", "name": "WildFire Malware and 10 others"},
            bundle=bundle,
            customer_code="JJ",
        )
        self.assertEqual(decision.escalation, "IR")
        self.assertFalse(decision.isolate_host)
        self.assertIn("malware_blocked_ir_review", decision.rule_hits)
        self.assertEqual(decision.playbook_id, "PB-IR-MALWARE-BLOCKED")

    def test_high_goes_l2(self) -> None:
        decision = apply_rules(
            case={"_id": "c3", "severity": "High", "name": "Suspicious login"},
            bundle={"summary": {"data": {"tactics": ["Initial Access"]}}},
            customer_code="JJ",
        )
        self.assertEqual(decision.escalation, "L2")
        self.assertTrue(should_create_ticket(decision))


class TestKnowledge(unittest.TestCase):
    def test_sigma_wildfire(self) -> None:
        hits = match_sigma_catalogue(
            case={"name": "WildFire Malware"},
            bundle=_malware_bundle(),
        )
        ids = [h.get("id") for h in hits]
        self.assertIn("SIGMA-WILDFIRE", ids)
        self.assertNotIn("SIGMA-WILDFIRE-BLOCKED", ids)

    def test_sigma_wildfire_blocked(self) -> None:
        bundle = {
            "alerts": {
                "data": {
                    "docs": [
                        {
                            "_source": {
                                "palo_alto_networks": {
                                    "category": "Malware",
                                    "name": "WildFire Malware",
                                    "action_pretty": "Prevented (Blocked)",
                                    "description": "Suspicious executable detected",
                                }
                            }
                        }
                    ]
                }
            }
        }
        hits = match_sigma_catalogue(
            case={"name": "WildFire Malware"},
            bundle=bundle,
        )
        ids = [h.get("id") for h in hits]
        self.assertIn("SIGMA-WILDFIRE-BLOCKED", ids)
        self.assertNotIn("SIGMA-WILDFIRE", ids)
        self.assertEqual(hits[0].get("playbook_id"), "PB-IR-MALWARE-BLOCKED")

    def test_asset_criticality_seeded_host(self) -> None:
        bundle = {
            "observables": {
                "observables": {"host": [{"hostname": "NGB-YuliHu", "ip": "192.168.0.125"}]}
            }
        }
        crit, matched = resolve_asset_criticality(bundle=bundle)
        self.assertEqual(crit, "medium")
        self.assertTrue(any("yulihu" in m.lower() for m in matched))

    def test_asset_criticality_dc(self) -> None:
        crit, matched = resolve_asset_criticality(bundle=_malware_bundle())
        self.assertEqual(crit, "critical")
        self.assertTrue(matched)

    def test_enrich_knowledge_hits(self) -> None:
        kn = enrich_knowledge(
            case={"_id": "c", "severity": "Critical", "name": "WildFire Malware"},
            bundle=_malware_bundle(),
            customer_code="JJ",
            history=[],
        )
        self.assertEqual(kn["asset_criticality"], "critical")
        self.assertTrue(kn["knowledge_hits"])
        self.assertTrue(kn["suggested_playbook"])


class TestDecisionStoreAndOutcome(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DecisionStore(Path(self.tmp.name) / "dec.sqlite")
        self.store.init()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_record_and_outcome(self) -> None:
        eid = self.store.record_decision(
            source_id="stellar",
            stellar_case_id="abc123",
            middleware_case_id="XSOC-JJ-260701-001",
            jira_key="AIXSOC-1",
            customer_code="JJ",
            decision={
                "action": "escalate",
                "escalation": "IR",
                "notify_customer": True,
                "isolate_host": True,
                "playbook_id": "PB-IR-MALWARE",
                "confidence": 0.9,
                "rule_hits": ["malware_critical_ir"],
                "knowledge_hits": ["SIGMA-WILDFIRE"],
            },
            context={"severity": "Critical", "display_name": "WildFire"},
            ai_sections={"executive_summary": "惡意樣本"},
        )
        self.assertTrue(eid)
        row = self.store.get_latest_by_jira_key("AIXSOC-1")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["playbook_id"], "PB-IR-MALWARE")
        self.assertEqual(row["ai_sections"]["executive_summary"], "惡意樣本")

        ok = self.store.record_outcome(
            jira_key="AIXSOC-1",
            true_positive=False,
            root_cause="授權軟體安裝",
            source="manual",
        )
        self.assertTrue(ok)
        row2 = self.store.get_by_event_id(eid)
        assert row2 is not None
        self.assertIs(row2["outcome_true_positive"], False)
        self.assertEqual(row2["outcome_root_cause"], "授權軟體安裝")

    def test_similar_contexts_are_tenant_scoped(self) -> None:
        for case_id, customer_code in (("a", "JJNET"), ("b", "JJEDR")):
            self.store.record_decision(
                source_id="stellar",
                stellar_case_id=case_id,
                customer_code=customer_code,
                decision={"action": "create_ticket", "escalation": "L1"},
                context={"display_name": case_id},
            )
        rows = self.store.list_similar_contexts(
            source_id="stellar",
            customer_code="JJNET",
        )
        self.assertEqual([row["stellar_case_id"] for row in rows], ["a"])

    def test_infer_fp(self) -> None:
        out = infer_outcome_from_text("判定為誤報 / false positive；root cause: IT patch")
        self.assertIs(out["true_positive"], False)
        self.assertIn("IT patch", out["root_cause"])

    def test_apply_outcome_from_jira(self) -> None:
        self.store.record_decision(
            source_id="stellar",
            stellar_case_id="c9",
            jira_key="AIXSOC-9",
            decision={"action": "create_ticket", "escalation": "L2", "rule_hits": []},
        )
        result = apply_outcome_from_jira(
            self.store,
            jira_key="AIXSOC-9",
            fields={
                "status": {"name": "Done"},
                "resolution": {"name": "Won't Do"},
                "description": "這是 false positive",
            },
        )
        self.assertTrue(result["updated"])
        self.assertIs(result["true_positive"], False)

    def test_outcome_from_resolution_tag(self) -> None:
        self.store.record_decision(
            source_id="stellar",
            stellar_case_id="c10",
            jira_key="AIXSOC-10",
            decision={"action": "escalate", "escalation": "IR", "rule_hits": []},
        )
        result = apply_outcome_from_jira(
            self.store,
            jira_key="AIXSOC-10",
            fields={
                "status": {"name": "Resolved"},
                "customfield_10201": {"value": "False Positive"},
            },
        )
        self.assertTrue(result["updated"])
        self.assertIs(result["true_positive"], False)
        self.assertEqual(result["resolution_tag"], "False Positive")
        # Unknown writeback must not wipe labeled FP
        result2 = apply_outcome_from_jira(
            self.store,
            jira_key="AIXSOC-10",
            fields={"status": {"name": "Resolved"}},
        )
        row = self.store.get_latest_by_jira_key("AIXSOC-10")
        assert row is not None
        self.assertIs(row["outcome_true_positive"], False)


class TestActionsAndPipeline(unittest.IsolatedAsyncioTestCase):
    def test_apply_jira_labels(self) -> None:
        fields = {"labels": ["stellar-cyber"], "summary": "x"}
        decision = DecisionResult(
            action="escalate",
            escalation="IR",
            playbook_id="PB-IR-MALWARE",
            jira_labels=["malware"],
            isolate_host=True,
            jira_priority="Highest",
            summary="test",
            rule_hits=["malware_critical_ir"],
        )
        out = apply_decision_to_jira_fields(fields, decision)
        self.assertIn("decision-ir", out["labels"])
        self.assertIn("isolation-advisory", out["labels"])
        self.assertEqual(out["priority"]["name"], "Highest")
        desc = out.get("description")
        if isinstance(desc, dict):
            self.assertNotIn("AIxSOC Decision", str(desc))

    def test_apply_jira_description_when_enabled(self) -> None:
        from unittest.mock import patch

        from app.config import StellarSettings

        fields = {
            "labels": ["stellar-cyber"],
            "summary": "x",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "案件編號: XSOC-1"}],
                    }
                ],
            },
        }
        decision = DecisionResult(
            action="escalate",
            escalation="IR",
            playbook_id="PB-IR-MALWARE",
            summary="test summary",
            rule_hits=["malware_critical_ir"],
        )
        settings = StellarSettings(decision_append_jira_description=True)
        with patch("app.config.get_stellar_settings", return_value=settings):
            out = apply_decision_to_jira_fields(fields, decision)
        self.assertIn("AIxSOC Decision", str(out.get("description")))

    async def test_evaluate_persists_seed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            store = DecisionStore(Path(tmp.name) / "d.sqlite")
            store.init()
            decision = await evaluate_case_decision(
                case={"_id": "cafe", "severity": "High", "name": "Suspicious PowerShell EncodedCommand"},
                bundle={
                    "alerts": {
                        "data": {
                            "docs": [
                                {
                                    "_source": {
                                        "palo_alto_networks": {
                                            "description": "powershell -EncodedCommand AAAA",
                                            "action_pretty": "Detected",
                                        }
                                    }
                                }
                            ]
                        }
                    },
                    "summary": {"data": {"tactics": ["Execution"]}},
                    "observables": {"observables": {"host": [{"hostname": "ws01"}]}},
                },
                source_id="stellar",
                customer_code="JJ",
                middleware_case_id="XSOC-JJ-001",
                store=store,
                run_ai=False,
                persist=True,
            )
            self.assertTrue(should_create_ticket(decision))
            self.assertTrue(decision.context_snapshot.get("decision_event_id"))
            row = store.get_latest_by_case("stellar", "cafe")
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row["stellar_case_id"], "cafe")
            # Phase 0 seed: context persisted
            self.assertTrue(row.get("context"))
        finally:
            tmp.cleanup()


class TestPilotReport(unittest.TestCase):
    def test_metrics_and_report(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            store = DecisionStore(Path(tmp.name) / "d.sqlite")
            store.init()
            for i, (esc, tp) in enumerate(
                [("L2", False), ("L2", True), ("IR", True), ("L1", False), ("L1", None)]
            ):
                eid = store.record_decision(
                    source_id="stellar",
                    stellar_case_id=f"case{i}",
                    jira_key=f"AIXSOC-{i}",
                    customer_code="JJ",
                    decision={
                        "action": "create_ticket" if esc != "IR" else "escalate",
                        "escalation": esc,
                        "notify_customer": esc != "L1",
                        "playbook_id": "PB-X",
                        "rule_hits": [],
                    },
                )
                if tp is not None or i < 4:
                    store.record_outcome(
                        event_id=eid,
                        true_positive=tp,
                        root_cause="x" if tp is False else "malware",
                    )
                else:
                    # Terminal stamp without TP/FP label (duty skipped resolution tag)
                    store.record_outcome(event_id=eid, true_positive=None, root_cause="")
            events = store.list_events(source_id="stellar")
            metrics = compute_decision_metrics(events)
            self.assertEqual(metrics["total_decisions"], 5)
            self.assertIsNotNone(metrics["mis_escalation_rate"])
            report = build_pilot_report(store, source_id="stellar", customer_code="JJ")
            self.assertIn("metrics", report)
            self.assertTrue(report["metrics"]["go_no_go_hints"])
            self.assertIn("unlabeled_resolved", report)
            self.assertGreaterEqual(report["metrics"].get("unlabeled_resolved_count", 0), 1)
            md = render_pilot_markdown(report)
            self.assertIn("Unlabeled resolved", md)
        finally:
            tmp.cleanup()


class TestDecisionJiraNotes(unittest.TestCase):
    def test_create_comment_mentions_tag(self) -> None:
        from app.decision.jira_notes import (
            CREATE_COMMENT_MARKER,
            format_decision_create_comment,
            format_outcome_reminder_comment,
            OUTCOME_REMINDER_MARKER,
        )

        text = format_decision_create_comment(
            DecisionResult(
                action="escalate",
                escalation="IR",
                playbook_id="PB-IR-MALWARE-BLOCKED",
                isolate_host=False,
                rule_hits=["malware_blocked_ir_review"],
                knowledge_hits=["SIGMA-WILDFIRE-BLOCKED"],
                summary="blocked malware review",
                notify_customer=True,
            ),
            middleware_case_id="XSOC-JJ-1",
            case={"severity": "Critical", "name": "WildFire Malware and 10 others"},
            bundle={
                "alerts": {
                    "data": {
                        "docs": [
                            {
                                "_source": {
                                    "palo_alto_networks": {
                                        "category": "Malware",
                                        "action_pretty": "Prevented (Blocked)",
                                    }
                                }
                            }
                        ]
                    }
                },
                "observables": {
                    "observables": {"host": [{"hostname": "NGB-YuliHu"}]}
                },
            },
        )
        self.assertIn("PB-IR-MALWARE-BLOCKED", text)
        self.assertIn("值班", text)
        self.assertIn("建議步驟", text)
        self.assertIn("不要先隔離", text)
        self.assertIn("NGB-YuliHu", text)
        self.assertIn("已阻擋", text)
        self.assertNotIn("Decision Dataset", text)
        self.assertIn(CREATE_COMMENT_MARKER, text)
        rem = format_outcome_reminder_comment(jira_key="AIXSOC-52")
        self.assertIn("AIXSOC-52", rem)
        self.assertIn("resolution tag", rem)
        self.assertIn(OUTCOME_REMINDER_MARKER, rem)

class TestDecisionAiBridge(unittest.IsolatedAsyncioTestCase):
    def test_brief_and_normalize(self) -> None:
        from app.decision.ai_bridge import brief_decision_for_ai, extract_ai_sections_blob, normalize_ai_sections

        d = DecisionResult(
            action="escalate",
            escalation="IR",
            playbook_id="PB-IR-MALWARE-BLOCKED",
            isolate_host=False,
            rule_hits=["malware_blocked_ir_review"],
        )
        brief = brief_decision_for_ai(d)
        assert brief is not None
        self.assertEqual(brief["playbook_id"], "PB-IR-MALWARE-BLOCKED")
        self.assertFalse(brief["isolate_host_advisory"])

        self.assertIsNone(normalize_ai_sections({"ok": False, "error": "x"}))
        self.assertEqual(
            normalize_ai_sections({"ok": True, "executive_summary": "a", "event_description": "b"})[
                "executive_summary"
            ],
            "a",
        )
        blob = extract_ai_sections_blob({"ai": {"ok": True, "executive_summary": "s"}})
        self.assertEqual(blob["executive_summary"], "s")

    async def test_precomputed_skips_llm(self) -> None:
        from app.decision.ai_bridge import generate_ai_aligned_with_decision

        settings = NotifySettings(soc_notify_ai_enabled=True, soc_notify_ai_api_key="k")
        with patch("app.ai.soc_notify.chat_completion_json", new=AsyncMock()) as mock_chat:
            out = await generate_ai_aligned_with_decision(
                case={"_id": "x"},
                bundle={},
                settings=settings,
                precomputed={
                    "executive_summary": "已有摘要",
                    "event_description": "已有描述",
                    "recommended_actions": ["確認"],
                },
            )
        mock_chat.assert_not_awaited()
        self.assertEqual(out.get("source"), "precomputed")
        self.assertEqual(out.get("executive_summary"), "已有摘要")

    async def test_evaluate_run_ai_passes_decision(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            store = DecisionStore(Path(tmp.name) / "d.sqlite")
            store.init()
            settings = NotifySettings(
                soc_notify_ai_enabled=True,
                soc_notify_ai_api_key="test-key",
            )
            mock_payload = {
                "executive_summary": "IR 已阻擋",
                "event_description": "WildFire",
                "recommended_actions": ["確認封鎖"],
            }
            with (
                patch("app.decision.pipeline.get_notify_settings", return_value=settings),
                patch(
                    "app.ai.soc_notify.chat_completion_json",
                    new=AsyncMock(return_value=mock_payload),
                ) as mock_chat,
            ):
                decision = await evaluate_case_decision(
                    case={"_id": "ai1", "severity": "Critical", "name": "WildFire Malware"},
                    bundle={
                        "alerts": {
                            "data": {
                                "docs": [
                                    {
                                        "_source": {
                                            "palo_alto_networks": {
                                                "category": "Malware",
                                                "name": "WildFire Malware",
                                                "action_pretty": "Prevented (Blocked)",
                                                "description": "Suspicious executable detected",
                                            }
                                        }
                                    }
                                ]
                            }
                        }
                    },
                    source_id="stellar",
                    customer_code="JJ",
                    store=store,
                    run_ai=True,
                    persist=True,
                )
            self.assertIsNotNone(decision.ai_sections)
            assert decision.ai_sections is not None
            self.assertIn("IR", decision.ai_sections["executive_summary"])
            user_prompt = mock_chat.await_args.kwargs["user_prompt"]
            self.assertIn("PB-IR-MALWARE-BLOCKED", user_prompt)
            row = store.get_latest_by_case("stellar", "ai1")
            assert row is not None
            self.assertIsNotNone(row.get("ai_json"))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
